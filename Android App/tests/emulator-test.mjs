#!/usr/bin/env node
/*
 * ACME Shop Android — emulator functional test harness.
 *
 * Prerequisites:
 *   - An AVD is booted and `adb install -r apk/ACME-Shop.apk` has run.
 *   - `adb forward tcp:9222 localabstract:webview_devtools_remote_<pid>` is set up
 *     (see run-tests.sh, which does all of the above).
 *
 * Drives the app through Chrome DevTools Protocol (Node 22 built-in WebSocket,
 * no npm dependencies) and full-device screenshots via `adb exec-out screencap`.
 * Writes results.json + screenshots into this folder's parent (screenshots/).
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = path.dirname(HERE);
const SHOTS = path.join(APP, 'screenshots');
const ADB = process.env.ADB || path.join(process.env.HOME, 'Library/Android/sdk/platform-tools/adb');
const CDP = process.env.CDP_PORT || '9222';
fs.mkdirSync(SHOTS, { recursive: true });

const adb = (...args) => execFileSync(ADB, args, { maxBuffer: 32 * 1024 * 1024 });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class Cdp {
  constructor(ws) {
    this.ws = ws;
    this.seq = 0;
    this.pending = new Map();
    this.consoleErrors = [];
    this.exceptions = [];
    this.failedRequests = [];
    this.badResponses = [];
    ws.addEventListener('message', (evt) => this.onMessage(JSON.parse(evt.data)));
  }
  onMessage(msg) {
    if (msg.id && this.pending.has(msg.id)) {
      const { resolve, reject } = this.pending.get(msg.id);
      this.pending.delete(msg.id);
      msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
      return;
    }
    switch (msg.method) {
      case 'Runtime.exceptionThrown':
        this.exceptions.push(msg.params?.exceptionDetails?.text || 'exception');
        break;
      case 'Runtime.consoleAPICalled':
        if (['error', 'warning'].includes(msg.params?.type)) {
          this.consoleErrors.push((msg.params.args || []).map((a) => a.value ?? a.description).join(' '));
        }
        break;
      case 'Log.entryAdded':
        if (['error', 'warning'].includes(msg.params?.entry?.level)) {
          this.consoleErrors.push(msg.params.entry.text);
        }
        break;
      case 'Network.loadingFailed':
        this.failedRequests.push(`${msg.params?.errorText}: ${msg.params?.type}`);
        break;
      case 'Network.responseReceived':
        if (msg.params?.response?.status >= 400) {
          this.badResponses.push(`${msg.params.response.status} ${msg.params.response.url}`);
        }
        break;
      default:
        break;
    }
  }
  send(method, params = {}) {
    const id = ++this.seq;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
      setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
          reject(new Error(`CDP timeout: ${method}`));
        }
      }, 30000);
    });
  }
  async evaluate(expression) {
    const r = await this.send('Runtime.evaluate', {
      expression, awaitPromise: true, returnByValue: true, userGesture: true,
    });
    if (r.exceptionDetails) {
      throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
    }
    return r.result?.value;
  }
}

async function connect() {
  const list = await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json();
  const page = list.find((t) => t.type === 'page' && t.url.includes('__acme_app__'));
  if (!page) throw new Error('No ACME WebView page target found (is the app running?)');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, { once: true });
    ws.addEventListener('error', reject, { once: true });
  });
  return new Cdp(ws);
}

const results = [];
function record(id, name, ok, detail) {
  results.push({ id, name, ok: !!ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${id.padEnd(5)} ${name}${detail ? ` — ${detail}` : ''}`);
}
async function test(id, name, fn) {
  try {
    const detail = await fn();
    record(id, name, true, detail);
  } catch (e) {
    record(id, name, false, String(e.message || e).slice(0, 400));
  }
}
const assert = (cond, msg) => { if (!cond) throw new Error(msg); };

async function waitFor(cdp, expression, timeout = 40000, label = expression) {
  const start = Date.now();
  let last;
  while (Date.now() - start < timeout) {
    try { last = await cdp.evaluate(expression); } catch { /* page may be reloading */ }
    if (last) return last;
    await sleep(350);
  }
  throw new Error(`timeout waiting for ${label} (last=${JSON.stringify(last)})`);
}

let shotNo = 0;
function shot(tag) {
  const file = path.join(SHOTS, `${String(++shotNo).padStart(2, '0')}-${tag}.png`);
  try {
    fs.writeFileSync(file, adb('exec-out', 'screencap', '-p'));
    return path.basename(file);
  } catch (e) {
    return `screenshot failed: ${e.message}`;
  }
}

const js = (s) => JSON.stringify(s);
const click = (cdp, selector) => cdp.evaluate(
  `(() => { const e = document.querySelector(${js(selector)}); if (!e) return false; e.click(); return true; })()`,
);
/** Click the last matching element (the most recent rendered card in the transcript). */
const clickLast = (cdp, selector) => cdp.evaluate(
  `(() => { const all = document.querySelectorAll(${js(selector)}); const e = all[all.length - 1]; if (!e) return false; e.click(); return true; })()`,
);
/** Click the first enabled match (out-of-stock Add buttons are disabled). */
const clickEnabled = (cdp, selector) => cdp.evaluate(
  `(() => { const e = [...document.querySelectorAll(${js(selector)})].find(x => !x.disabled); if (!e) return false; e.click(); return true; })()`,
);
const turnDone = (n) => `(() => { const s = window.__acme && window.__acme.snapshot(); `
  + `return s && !s.streaming && s.turns.length >= ${n} && s.turns.every(t => !t.streaming); })()`;

/** The hosted LLM occasionally finishes a tool-only turn; rephrase until a card appears. */
async function searchUntilProducts(cdp, maxAttempts = 3) {
  const prompts = [
    'Show me coffee makers under $150',
    'Find coffee makers under $150 and show me the results',
    'Search the catalog for a coffee maker under $150',
  ];
  for (let i = 0; i < maxAttempts; i++) {
    const n = await cdp.evaluate('window.__acme.snapshot().turns.length');
    await cdp.evaluate(`void window.__acme.send(${js(prompts[i % prompts.length])})`);
    await waitFor(cdp, turnDone(n + 1), 90000, 'search chat turn');
    const s = await cdp.evaluate('window.__acme.snapshot()');
    if (s.turns.at(-1).cards.includes('products')) return i + 1;
  }
  return 0;
}

async function main() {
  const cdp = await connect();
  await cdp.send('Runtime.enable');
  await cdp.send('Log.enable');
  await cdp.send('Network.enable');
  await cdp.send('Page.enable');

  // Start every run from a clean page so turn counters and cart state are deterministic.
  await cdp.send('Page.reload', { ignoreCache: true });
  await sleep(1200);

  await test('T01', 'App boots on shop origin with live API data', async () => {
    const info = await waitFor(cdp,
      `(() => { const s = window.__acme && window.__acme.snapshot(); return s && s.connected ? s : null; })()`,
      30000, 'connected');
    const env = await cdp.evaluate('window.__androidInfo()');
    assert(env.platform === 'Android' && env.bridge, 'Android bridge missing');
    assert(env.origin === 'https://shop.mimi.money', `wrong origin: ${env.origin}`);
    assert(info.catalogCount >= 80, `catalog too small: ${info.catalogCount}`);
    assert(info.orderCount >= 1, 'orders not loaded');
    assert(info.memoryCount >= 1, 'memory facts not loaded');
    assert(info.sessionId, 'no session id');
    return `${info.catalogCount} products, ${info.orderCount} orders, ${info.memoryCount} facts, shopper ${info.shopper.name}, model ${info.health?.model}`;
  });

  shot('home');

  await test('T02', 'Native shell + Android shim diagnostics', async () => {
    const d = await cdp.evaluate(`({
      voice: typeof window.SpeechRecognition,
      bridgeMethods: typeof AndroidShop.startVoice === 'function'
        && typeof AndroidShop.openExternal === 'function'
        && typeof AndroidShop.setOnline === 'function',
      app: JSON.parse(AndroidShop.appInfo()),
      title: document.title,
      assets: performance.getEntriesByType('resource').filter(r => r.name.includes('__acme_app__')).length,
    })`);
    assert(d.voice === 'function', 'speech shim missing');
    assert(d.bridgeMethods, 'JavascriptInterface methods missing');
    assert(d.app.upstream === 'https://shop.mimi.money', 'appInfo wrong');
    assert(d.assets >= 4, `bundled assets not served (${d.assets})`);
    return `${d.assets} local assets served under ${await cdp.evaluate('location.origin')}, voice shim + bridge OK`;
  });

  await test('T03', 'Assistant SSE turn: product search card + tool steps + suggestions', async () => {
    // The hosted model occasionally ends a turn after tool calls without presenting a
    // card (the web portal behaves identically). Retry like a shopper would rephrase.
    const attempts = await searchUntilProducts(cdp);
    const s = await cdp.evaluate('window.__acme.snapshot()');
    const last = s.turns.at(-1);
    assert(!last.error, `turn error: ${last.error}`);
    assert(last.cards.includes('products'), `no product card after ${attempts} attempts: ${last.cards}`);
    assert(last.steps.length > 0, 'no tool activity recorded');
    assert(s.suggestions.length > 0, 'no follow-up suggestions');
    return `${attempts} attempt(s), cards=[${last.cards}], ${last.steps.length} tool steps, ${s.suggestions.length} suggestions`;
  });

  shot('assistant-products');

  await test('T04', 'Product detail modal (GET /api/products/{id})', async () => {
    const opened = await clickLast(cdp, '[data-component="products"] [data-action="product"]');
    assert(opened, 'no product detail trigger in card');
    await waitFor(cdp, `!document.getElementById('modal').hidden && document.querySelector('#modal-body .card, #modal-body h2, #modal-body h3') !== null`, 15000, 'modal');
    const body = await cdp.evaluate(`document.getElementById('modal-body').innerText.slice(0, 300)`);
    assert(body.length > 20, 'modal is empty');
    shot('product-detail');
    await click(cdp, '#modal-close');
    assert(await cdp.evaluate(`document.getElementById('modal').hidden`), 'modal did not close');
    return body.replace(/\s+/g, ' ').slice(0, 90);
  });

  await test('T05', 'Add to cart from product card (provenance gate honoured)', async () => {
    const before = await cdp.evaluate('window.__acme.snapshot().cart.item_count');
    const clicked = await clickEnabled(cdp, '[data-component="products"] [data-action="add"]');
    assert(clicked, 'no enabled Add button in product card');
    await waitFor(cdp, `window.__acme.snapshot().cart.item_count > ${before}`, 15000, 'cart increment');
    const c = await cdp.evaluate('window.__acme.snapshot().cart');
    assert(c.items.length > 0, 'cart has no lines');
    return `item_count ${before} -> ${c.item_count}, subtotal ${c.subtotal} ${c.currency}`;
  });

  await test('T06', 'Cart panel: lines, totals, quantity stepper drives a chat turn', async () => {
    await click(cdp, '#cart-toggle');
    assert(await cdp.evaluate('window.__acme.state.cartOpen'), 'cart panel did not open');
    const lines = await cdp.evaluate(`document.querySelectorAll('#cart-body [data-action="qty"]').length`);
    assert(lines > 0, 'no quantity controls in cart');
    shot('cart');
    const before = await cdp.evaluate('window.__acme.snapshot().cart.item_count');
    const turns = await cdp.evaluate('window.__acme.snapshot().turns.length');
    // Keep the cart non-empty and under the host's $250 checkout ceiling: step down when
    // it is already large, otherwise step up.
    const delta = before >= 3 ? '-1' : '1';
    await click(cdp, `[data-action="qty"][data-delta="${delta}"]`);
    await waitFor(cdp, turnDone(turns + 1), 60000, 'quantity change turn');
    const after = await cdp.evaluate('window.__acme.snapshot().cart.item_count');
    assert(after !== before, `quantity did not change (${before} -> ${after})`);
    await click(cdp, '#cart-toggle'); // close the cart so the transcript is visible
    return `${lines} qty controls, item_count ${before} -> ${after} via agent chat, subtotal kept under host cap`;
  });

  await test('T07', 'Checkout card: staged, not charged, PayPal handoff link', async () => {
    if (await cdp.evaluate('window.__acme.state.cartOpen')) await click(cdp, '#cart-toggle');
    // The host refuses checkout above its $250 ceiling. Rebuild a small, provenance-backed
    // cart when a prior run left the shared demo cart empty or over that cap.
    let cart = await cdp.evaluate('window.__acme.snapshot().cart');
    if (!cart.items.length || Number(cart.subtotal) > 250) {
      await cdp.evaluate(`window.__acme.api.reset({})`);
      await cdp.evaluate(`window.__acme.state.sessionId = window.__acme.api.session; void window.__acme.refreshCart()`);
      assert(await searchUntilProducts(cdp) > 0, 'no product card while rebuilding cart');
      assert(await clickEnabled(cdp, '[data-component="products"] [data-action="add"]'),
        'no enabled Add button for cart rebuild');
      await waitFor(cdp, `window.__acme.snapshot().cart.items.length > 0`, 15000, 'cart rebuild');
      cart = await cdp.evaluate('window.__acme.snapshot().cart');
    }
    assert(Number(cart.subtotal) > 0 && Number(cart.subtotal) <= 250,
      `cart not within host cap: ${cart.subtotal}`);
    const turns = await cdp.evaluate('window.__acme.snapshot().turns.length');
    await cdp.evaluate(`void window.__acme.send(${js('Check out my cart.')})`);
    await waitFor(cdp, turnDone(turns + 1), 60000, 'checkout turn');
    const card = await cdp.evaluate(`(() => { const c = document.querySelector('[data-checkout-card]'); return c ? c.innerText : null; })()`);
    assert(card, 'no checkout card rendered');
    assert(/Not charged/i.test(card), 'missing "Not charged" disclosure');
    assert(/Pay securely with PayPal/i.test(card), 'missing PayPal approval link');
    const href = await cdp.evaluate(`(() => { const a = document.querySelector('[data-checkout-card] [data-action="open-url"]'); return a ? a.dataset.url : null; })()`);
    assert(href && /^https?:\/\//.test(href), 'PayPal handoff URL missing');
    shot('checkout');
    return `subtotal shown, "Not charged" disclosure, handoff ${href.slice(0, 70)}… (no real order created)`;
  });

  await test('T08', 'Orders view: list, status chips and filters', async () => {
    await cdp.evaluate(`window.__acme.setView('orders')`);
    await waitFor(cdp, `document.querySelectorAll('#orders-view .order-row').length > 0`, 10000, 'orders rows');
    const all = await cdp.evaluate(`document.querySelectorAll('#orders-view .order-row').length`);
    const filters = await cdp.evaluate(`[...document.querySelectorAll('[data-action="order-filter"]')].map(b => b.dataset.filter)`);
    assert(filters.length === 4, `unexpected filters: ${filters}`);
    await click(cdp, '[data-action="order-filter"][data-filter="delayed"]');
    const delayed = await cdp.evaluate(`window.__acme.state.orderFilter`);
    assert(delayed === 'delayed', 'filter not applied');
    shot('orders');
    await click(cdp, '[data-action="order-filter"][data-filter="all"]');
    return `${all} orders, filters ${filters.join('/')}, delayed filter applied`;
  });

  await test('T09', 'Activity sheet shows per-turn tool trace', async () => {
    await cdp.evaluate(`window.__acme.openSheet('activity')`);
    await waitFor(cdp, `!document.getElementById('sheet').hidden`, 5000, 'activity sheet');
    const text = await cdp.evaluate(`document.getElementById('sheet-body').innerText`);
    assert(text.length > 20, 'activity sheet empty');
    assert(/Tool|tool|Search|search|step/i.test(text), 'no tool trace in activity sheet');
    await click(cdp, '#sheet-close');
    return text.replace(/\s+/g, ' ').slice(0, 90);
  });

  await test('T10', 'Memory sheet: PATCH round-trip with restore', async () => {
    await cdp.evaluate(`window.__acme.openSheet('account')`);
    await waitFor(cdp, `document.querySelectorAll('#sheet-body .fact-row').length > 0`, 8000, 'fact rows');
    const key = await cdp.evaluate(`document.querySelector('#sheet-body .fact-row').dataset.key`);
    const original = await cdp.evaluate(`window.__acme.state.memory.find(f => f.key === ${js(key)})?.value`);
    assert(original != null, 'could not read original memory fact');
    // Fill + save twice: first a temporary value, then the original (restore).
    await cdp.evaluate(`(() => { const row = [...document.querySelectorAll('#sheet-body .fact-row')].find(r => r.dataset.key === ${js(key)}); row.querySelector('[data-action="fact-edit"]').click(); row.querySelector('.fact-editor textarea').value = ${js('Android emulator test value')}; return true; })()`);
    await click(cdp, '#sheet-body .fact-editor:not([hidden]) [data-action="fact-save"]');
    await waitFor(cdp, `window.__acme.state.memory.find(f => f.key === ${js(key)})?.value === ${js('Android emulator test value')}`, 15000, 'memory PATCH');
    await cdp.evaluate(`(() => { const row = [...document.querySelectorAll('#sheet-body .fact-row')].find(r => r.dataset.key === ${js(key)}); row.querySelector('[data-action="fact-edit"]').click(); row.querySelector('.fact-editor textarea').value = ${js(original)}; return true; })()`);
    await click(cdp, '#sheet-body .fact-editor:not([hidden]) [data-action="fact-save"]');
    await waitFor(cdp, `window.__acme.state.memory.find(f => f.key === ${js(key)})?.value === ${js(original)}`, 15000, 'memory restore');
    shot('memory');
    await click(cdp, '#sheet-close');
    return `fact "${key}" edited and restored to its original value (no shared data changed)`;
  });

  await test('T11', 'Settings sheet: host status, base URL, session reset', async () => {
    await cdp.evaluate(`window.__acme.openSheet('settings')`);
    await waitFor(cdp, `document.getElementById('api-base') !== null`, 8000, 'settings sheet');
    const base = await cdp.evaluate(`document.getElementById('api-base').value`);
    assert(base === 'https://shop.mimi.money', `wrong base: ${base}`);
    const status = await cdp.evaluate(`document.getElementById('sheet-body').innerText`);
    assert(/PayPal|paypal/i.test(status), 'payments status missing');
    const oldSession = await cdp.evaluate('window.__acme.snapshot().sessionId');
    await click(cdp, '[data-action="reset-session"]');
    await waitFor(cdp, `window.__acme.snapshot().sessionId !== ${js(oldSession)}`, 15000, 'session reset');
    const s = await cdp.evaluate('window.__acme.snapshot()');
    assert(s.connected, 'disconnected after reset');
    shot('settings');
    await click(cdp, '#sheet-close');
    return `POST /api/reset issued a new session (${oldSession.slice(0, 8)}… -> ${s.sessionId.slice(0, 8)}…), cart reset`;
  });

  await test('T12', 'Suggestion chip starts a new streaming turn', async () => {
    const turns = await cdp.evaluate('window.__acme.snapshot().turns.length');
    const chip = await cdp.evaluate(`(() => { const c = document.querySelector('#suggestions [data-action="ask"]'); if (!c) return null; const t = c.dataset.prompt; c.click(); return t; })()`);
    assert(chip, 'no suggestion chip available');
    await waitFor(cdp, turnDone(turns + 1), 60000, 'chip turn');
    const s = await cdp.evaluate('window.__acme.snapshot()');
    assert(!s.turns.at(-1).error, `chip turn error: ${s.turns.at(-1).error}`);
    return `chip "${chip.slice(0, 50)}…" completed with ${s.turns.at(-1).textLength} chars`;
  });

  await test('T13', 'Voice shim delivers native speech result into composer', async () => {
    const value = await cdp.evaluate(`(() => {
      const r = new SpeechRecognition();
      window.__androidVoice = r;
      r.onstart && r.onstart({ type: 'start' });
      r.onresult = (e) => { window.__voiceResult = e.results[0][0].transcript; };
      r.onend = () => { window.__voiceEnded = true; };
      window.__androidVoiceResult('find me a tent under 250 dollars', null);
      return { result: window.__voiceResult, ended: window.__voiceEnded };
    })()`);
    assert(value.result === 'find me a tent under 250 dollars', 'speech result not delivered');
    assert(value.ended === true, 'speech onend not fired');
    const errPath = await cdp.evaluate(`(() => {
      const r = new SpeechRecognition(); window.__androidVoice = r;
      r.onerror = (e) => { window.__voiceError = e.error; };
      window.__androidVoiceResult(null, 'no-speech');
      return window.__voiceError;
    })()`);
    assert(errPath === 'no-speech', 'speech error path broken');
    return 'native SpeechRecognizer -> Web Speech API shim success + error paths OK';
  });

  await test('T14', 'Hardware back closes a sheet without leaving the app', async () => {
    await cdp.evaluate(`window.__acme.openSheet('activity')`);
    assert(!await cdp.evaluate(`document.getElementById('sheet').hidden`), 'sheet not open');
    adb('shell', 'input', 'keyevent', '4');
    await waitFor(cdp, `document.getElementById('sheet').hidden`, 8000, 'back closes sheet');
    const resumed = adb('shell', 'dumpsys', 'activity', 'activities').toString();
    assert(/com\.acme\.shop/.test(resumed), 'app was finished by back press');
    return 'back consumed by sheet; MainActivity still resumed';
  });

  await test('T15', 'Native header buttons: settings and cart', async () => {
    // Buttons live in the native header above the WebView (device coords, 1280x2856).
    adb('shell', 'input', 'tap', '1103', '235'); // Settings (gear)
    await waitFor(cdp, `!document.getElementById('sheet').hidden && document.getElementById('sheet-title').textContent === 'Settings'`, 8000, 'native settings');
    await click(cdp, '#sheet-close');
    if (await cdp.evaluate('window.__acme.state.cartOpen')) await click(cdp, '#cart-toggle');
    adb('shell', 'input', 'tap', '1205', '235'); // Cart (hamburger glyph)
    await waitFor(cdp, `window.__acme.state.cartOpen === true`, 8000, 'native cart');
    await click(cdp, '#cart-toggle');
    return 'native header settings + cart buttons drive the WebView';
  });

  await test('T16', 'Offline path shows banner, retry reconnects', async () => {
    await cdp.send('Network.emulateNetworkConditions', {
      offline: true, latency: 0, downloadThroughput: 0, uploadThroughput: 0,
    });
    await cdp.evaluate(`(() => { window.__acme.state.connected = false; document.getElementById('connection-retry').click(); return true; })()`);
    await waitFor(cdp, `!document.getElementById('connection-banner').hidden`, 20000, 'offline banner');
    const banner = await cdp.evaluate(`document.getElementById('connection-message').textContent`);
    shot('offline');
    await cdp.send('Network.emulateNetworkConditions', {
      offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1,
    });
    await click(cdp, '#connection-retry');
    await waitFor(cdp, `window.__acme.snapshot().connected && document.getElementById('connection-banner').hidden`, 30000, 'reconnect');
    return `offline banner ("${banner.slice(0, 60)}…") then retry restored LIVE`;
  });

  await test('T17', 'Final state: still online, no runtime exceptions', async () => {
    const s = await cdp.evaluate('window.__acme.snapshot()');
    assert(s.connected && s.catalogCount >= 80, 'final state degraded');
    const nativeErrors = adb('logcat', '-d', '-t', '4000').toString();
    const crashes = (nativeErrors.match(/FATAL EXCEPTION|Process: com\.acme\.shop.*Has died/g) || []);
    assert(crashes.length === 0, `native crash detected: ${crashes[0]}`);
    shot('final-state');
    return `connected, ${s.catalogCount} products, ${s.orderCount} orders, ${s.turns.length} chat turns`;
  });

  const diagnostics = {
    consoleErrors: cdp.consoleErrors,
    exceptions: cdp.exceptions,
    failedRequests: cdp.failedRequests,
    badResponses: cdp.badResponses,
  };
  await test('T18', 'Zero JS exceptions / console errors / HTTP failures', async () => {
    const real = cdp.consoleErrors.filter((e) => !/favicon|net::ERR_INTERNET_DISCONNECTED|ERR_NETWORK_CHANGED/.test(e));
    const bad = cdp.badResponses.filter((r) => !/favicon/.test(r));
    assert(cdp.exceptions.length === 0, `exceptions: ${cdp.exceptions.join(' | ')}`);
    assert(real.length === 0, `console: ${real.slice(0, 3).join(' | ')}`);
    assert(bad.length === 0, `HTTP errors: ${bad.slice(0, 3).join(' | ')}`);
    return 'clean (network-disconnect noise from the offline test excluded)';
  });

  const passed = results.filter((r) => r.ok).length;
  const summary = {
    runAt: new Date().toISOString(),
    device: adb('shell', 'getprop', 'ro.product.model').toString().trim(),
    android: adb('shell', 'getprop', 'ro.build.version.release').toString().trim(),
    appVersion: '1.0.0',
    total: results.length, passed, failed: results.length - passed,
    results, diagnostics,
  };
  fs.writeFileSync(path.join(HERE, 'results.json'), JSON.stringify(summary, null, 2) + '\n');
  console.log(`\n${passed}/${results.length} checks passed. Results: ${path.join(HERE, 'results.json')}`);
  process.exit(passed === results.length ? 0 : 1);
}

main().catch((e) => { console.error('HARNESS ERROR:', e); process.exit(2); });
