// ACME Shop — full storefront client, bundled in the Android app's assets/ and served
// by MainActivity under https://shop.mimi.money/__acme_app__/ (same-origin with /api/).
import { ShopApi, DEFAULT_BASE, loadBase, saveBase, clearSession } from './api.js';
import * as UI from './ui.js';

const $ = (id) => document.getElementById(id);
const els = {
  home: $('home'), transcript: $('transcript'), ordersView: $('orders-view'),
  suggestions: $('suggestions'), composerWrap: document.querySelector('.composer-wrap'),
  input: $('composer-input'), send: $('send-btn'), stop: $('stop-btn'), voice: $('voice-btn'),
  hint: $('composer-hint'),
  cartPanel: $('cart-panel'), cartBody: $('cart-body'), cartFooter: $('cart-footer'),
  sheet: $('sheet'), sheetTitle: $('sheet-title'), sheetBody: $('sheet-body'), scrim: $('scrim'),
  modal: $('modal'), modalBody: $('modal-body'), toast: $('toast'),
  banner: $('connection-banner'), bannerMessage: $('connection-message'),
  statusPill: $('status-pill'), statusText: $('status-text'),
  activityBtn: $('activity-btn'), activityBadge: $('activity-badge'),
  ordersBadge: $('orders-badge'), cartToggle: $('cart-toggle'), cartTopCount: $('cart-top-count'),
  accountName: $('account-name'), accountTier: $('account-tier'), accountAvatar: $('account-avatar'),
};

const state = {
  base: DEFAULT_BASE,
  sessionId: null,
  shopper: { name: 'there', tier: '' },
  health: null,
  catalog: [],
  cart: { items: [], item_count: 0, subtotal: 0, currency: 'USD' },
  orders: null,
  ordersFailed: false,
  memory: [],
  newMemoryKeys: new Set(),
  view: 'assistant',
  orderFilter: 'all',
  turns: [],
  streaming: false,
  suggestions: [],
  sheet: null,
  activityIndex: 0,
  checkoutStaged: false,
  cartOpen: false,
  connected: false,
  modalOpen: false,
};

const api = new ShopApi(state.base);
api.onSession = () => { state.sessionId = api.session; };
const turnDom = new Map(); // turn.id -> { root, text, cards, activity, error, slots: Map }
let controller = null;
let recognition = null;
let listening = false;
let voiceSupported = true;
let toastTimer = null;
let pendingText = null;
let memoryTimer = null;

/* ---------------- small utilities ---------------- */
function hydrateIcons(root = document) {
  root.querySelectorAll('[data-icon]').forEach((el) => {
    if (!el.dataset.hydrated) { el.innerHTML = UI.icon(el.dataset.icon, 16); el.dataset.hydrated = '1'; }
  });
}
function toast(message) {
  els.toast.textContent = message;
  els.toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { els.toast.hidden = true; }, 3200);
}
function openExternal(url) {
  if (!/^https?:\/\//.test(url)) return;
  if (chrome.tabs?.create) chrome.tabs.create({ url });
  else window.open(url, '_blank', 'noopener,noreferrer');
}
function scrollBottom(smooth = true) {
  els.transcript.scrollTo({ top: els.transcript.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
}
function setBanner(message) {
  els.banner.hidden = !message;
  els.bannerMessage.textContent = message || '';
}

/* ---------------- boot ---------------- */
async function boot() {
  state.base = await loadBase();
  api.setBase(state.base);
  setStatus('connecting', 'Connecting…');
  try {
    state.health = await api.getHealth();
    if (!state.health?.ok) throw new Error('The shop API did not report a healthy status.');
    state.shopper = await api.ensureSession();
    state.sessionId = api.session;
    const [products, cart, orders, memory] = await Promise.all([
      api.getProducts(100), api.getCart(), api.getOrders(), api.getMemory(),
    ]);
    state.catalog = products?.products || [];
    if (cart) state.cart = cart;
    state.orders = orders?.orders ?? null;
    state.ordersFailed = state.orders === null;
    state.memory = memory?.facts || [];
    state.connected = true;
    setBanner('');
    setStatus('online', `Connected · ${state.health.model || 'ACME'}`);
  } catch (err) {
    state.connected = false;
    setStatus('offline', 'Offline');
    setBanner(`Couldn't reach the shop API at ${state.base}. ${err.message || ''}`);
  }
  renderAll();
}
function setStatus(kind, text) {
  els.statusPill.classList.remove('online', 'offline');
  if (kind !== 'connecting') els.statusPill.classList.add(kind);
  els.statusText.textContent = text;
  if (window.AndroidShop) {
    try { AndroidShop.setOnline(kind === 'online'); } catch (e) { /* bridge not ready */ }
  }
}

async function refreshCart() {
  try { const c = await api.getCart(); if (c) { state.cart = c; renderCart(); } } catch { /* keep last good */ }
}
async function refreshMemory(markNew = false) {
  try {
    const m = await api.getMemory();
    const next = m?.facts || [];
    if (markNew) {
      const before = new Set(state.memory.map((f) => f.key));
      next.forEach((f) => { if (!before.has(f.key)) state.newMemoryKeys.add(f.key); });
    }
    state.memory = next;
    renderHeader();
    if (state.sheet) renderSheet();
  } catch { /* keep last good */ }
}

/* ---------------- rendering ---------------- */
function renderAll() {
  hydrateIcons();
  renderHeader();
  renderHomeOrTranscript();
  renderOrders();
  renderCart();
  renderSuggestions();
  renderComposer();
  renderSheet();
}
function renderHeader() {
  els.accountName.textContent = state.shopper.name;
  els.accountTier.textContent = state.shopper.tier;
  els.accountAvatar.textContent = (state.shopper.name || '?')[0];
  els.cartTopCount.textContent = state.cart.item_count || 0;
  const late = UI.upcoming(state.orders || []).filter((o) => o.status === 'delayed').length;
  els.ordersBadge.hidden = late === 0;
  els.ordersBadge.textContent = late;
  els.activityBtn.classList.toggle('busy', state.streaming);
  els.activityBadge.hidden = state.newMemoryKeys.size === 0;
  els.activityBadge.textContent = state.newMemoryKeys.size;
  els.statusPill.title = `${state.base} · ${state.health?.model || 'unknown model'}`;
}
function renderHomeOrTranscript() {
  const hasTurns = state.turns.length > 0;
  els.home.hidden = hasTurns;
  els.transcript.hidden = !hasTurns;
  if (!hasTurns) els.home.innerHTML = UI.renderHome(state, api);
  hydrateIcons(els.home);
}
function ensureTranscriptInner() {
  let inner = els.transcript.querySelector('.transcript-inner');
  if (!inner) {
    inner = document.createElement('div');
    inner.className = 'transcript-inner';
    els.transcript.appendChild(inner);
  }
  return inner;
}
function renderOrders() {
  els.ordersView.innerHTML = UI.renderOrders(state, api, state.orderFilter);
  hydrateIcons(els.ordersView);
}
function renderCart() {
  els.cartBody.innerHTML = UI.renderCartBody(state, api);
  els.cartFooter.innerHTML = UI.renderCartFooter(state);
  els.cartPanel.classList.toggle('collapsed', !state.cartOpen);
  hydrateIcons(els.cartBody);
  hydrateIcons(els.cartFooter);
}
function renderSuggestions() {
  const chips = state.suggestions || [];
  els.suggestions.hidden = chips.length === 0 || state.streaming;
  els.suggestions.innerHTML = chips.length
    ? `<div class="suggestions-inner">${chips.map((c) => `<button type="button" class="chip" data-action="ask" data-prompt="${UI.esc(c)}">${UI.esc(c)}</button>`).join('')}</div>`
    : '';
}
function renderComposer() {
  const busy = state.streaming;
  els.input.placeholder = busy ? 'Working…'
    : state.view === 'orders' ? 'Ask about an order, a return, a delivery…'
      : 'Ask about a product, a project, an order…';
  els.input.disabled = false;
  els.send.disabled = busy || !els.input.value.trim() || !state.connected;
  els.stop.hidden = !busy;
  els.send.hidden = busy;
  els.voice.disabled = busy || !voiceSupported;
  els.voice.classList.toggle('listening', listening);
  els.voice.title = voiceSupported ? 'Voice input (English)' : 'Voice input is not available in this browser';
}
function renderSheet() {
  if (!state.sheet) { els.sheet.hidden = true; els.scrim.hidden = true; return; }
  els.sheet.hidden = false;
  els.scrim.hidden = false;
  const titles = { activity: 'Activity', account: 'Profile & memory', settings: 'Settings' };
  els.sheetTitle.textContent = titles[state.sheet] || '';
  els.sheetBody.innerHTML = state.sheet === 'activity' ? UI.renderActivitySheet(state)
    : state.sheet === 'account' ? UI.renderAccountSheet(state)
      : UI.renderSettingsSheet(state);
  hydrateIcons(els.sheetBody);
}
function openSheet(name) {
  state.sheet = name;
  if (name === 'activity') state.activityIndex = Math.max(0, state.turns.length - 1);
  if (name === 'account') void refreshMemory();
  renderSheet();
}
function closeSheet() { state.sheet = null; renderSheet(); }
function openModal(html) {
  state.modalOpen = true;
  els.modalBody.innerHTML = html;
  els.modal.hidden = false;
  hydrateIcons(els.modalBody);
}
function closeModal() { state.modalOpen = false; els.modal.hidden = true; els.modalBody.innerHTML = ''; }

function setView(view) {
  state.view = view;
  document.querySelectorAll('.view-btn').forEach((b) => {
    const active = b.dataset.view === view;
    b.classList.toggle('active', active);
    if (active) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
  });
  $('assistant-view').hidden = view !== 'assistant';
  els.ordersView.hidden = view !== 'orders';
  els.composerWrap.hidden = view !== 'assistant';
  els.suggestions.hidden = view !== 'assistant' || !(state.suggestions || []).length || state.streaming;
  renderComposer();
}

/* ---------------- chat turn ---------------- */
let turnSeq = 0;
function startTurn(message) {
  const turn = {
    id: ++turnSeq, user: message, text: '', cards: [], steps: [], usage: null,
    elapsed_ms: 0, streaming: true, error: null, cardSeq: 0,
  };
  state.turns.push(turn);
  state.suggestions = [];
  renderSuggestions();

  const root = document.createElement('div');
  root.className = 'turn';
  root.dataset.turnId = String(turn.id);
  root.innerHTML = `<div class="user-row"><div class="user-bubble">${UI.esc(message)}</div></div>
    <div class="assistant-row">
      <div class="assistant-mark"><span class="mark-dot">${UI.icon('spark', 13)}</span><span style="font-size:11px;font-weight:700">ACME Assistant</span></div>
      <div class="assistant-text streaming-caret"></div>
      <div class="cards"></div>
      <div class="activity-line"><span class="pulse-dot"></span><span class="activity-label">Working…</span></div>
      <div class="error-bubble" hidden></div>
    </div>`;
  ensureTranscriptInner().appendChild(root);
  const nodes = {
    root,
    text: root.querySelector('.assistant-text'),
    cards: root.querySelector('.cards'),
    activity: root.querySelector('.activity-line'),
    activityLabel: root.querySelector('.activity-label'),
    error: root.querySelector('.error-bubble'),
    slots: new Map(),
  };
  turnDom.set(turn.id, nodes);
  const wide = true;
  const inner = els.transcript.querySelector('.transcript-inner');
  if (inner) inner.classList.toggle('wide', wide);
  els.home.hidden = true;
  els.transcript.hidden = false;
  scrollBottom(false);
  return turn;
}
function scheduleText(turn) {
  if (pendingText) return;
  pendingText = requestAnimationFrame(() => {
    pendingText = null;
    for (const [id, nodes] of turnDom) {
      const t = state.turns.find((x) => x.id === id);
      if (!t) continue;
      nodes.text.innerHTML = UI.markdown(t.text);
      nodes.text.classList.toggle('streaming-caret', t.streaming && !!t.text);
    }
  });
}
function activityFor(turn) {
  const running = (turn.steps || []).find((s) => s.status === 'running');
  const nodes = turnDom.get(turn.id);
  if (!nodes) return;
  if (running) {
    nodes.activity.hidden = false;
    nodes.activityLabel.textContent = running.label || `Running ${running.tool}…`;
  } else if (turn.streaming) {
    nodes.activity.hidden = false;
    nodes.activityLabel.textContent = 'Putting the answer together…';
  } else {
    nodes.activity.hidden = true;
  }
}
function slotFor(turn, component, streamId) {
  const nodes = turnDom.get(turn.id);
  if (!nodes) return null;
  let slot = null;
  if (streamId && nodes.slots.has(`id:${streamId}`)) slot = nodes.slots.get(`id:${streamId}`);
  if (!slot) {
    slot = [...nodes.slots.values()].find((s) => !s.dataset.final && s.dataset.slotComponent === component);
  }
  if (!slot) {
    slot = document.createElement('div');
    slot.className = 'card-slot';
    slot.dataset.slotComponent = component;
    if (component === 'comparison' || component === 'plan') slot.classList.add('wide-slot');
    nodes.cards.appendChild(slot);
    nodes.slots.set(`n:${turn.cardSeq++}`, slot);
  }
  if (streamId) nodes.slots.set(`id:${streamId}`, slot);
  return slot;
}
function handleEvent(turn, ev) {
  const d = ev.data || {};
  switch (ev.type) {
    case 'text_delta':
      turn.text += d.text || '';
      scheduleText(turn);
      scrollBottom();
      break;
    case 'progress':
      if (d.message) {
        const nodes = turnDom.get(turn.id);
        if (nodes) { nodes.activity.hidden = false; nodes.activityLabel.textContent = d.message; }
      }
      break;
    case 'tool_call': {
      const step = { tool: d.tool, id: d.id, input: d.input, label: d.label, status: 'running', started: performance.now() };
      turn.steps.push(step);
      activityFor(turn);
      break;
    }
    case 'tool_result': {
      const step = [...turn.steps].reverse().find((s) => s.id === d.id) || turn.steps.at(-1);
      if (step) {
        step.status = d.is_error ? 'error' : (d.status === 'blocked' ? 'blocked' : d.status || 'ok');
        step.summary = d.summary; step.reason = d.reason; step.excerpt = d.excerpt;
        step.elapsed = Math.round(performance.now() - step.started);
      }
      activityFor(turn);
      if (state.sheet === 'activity') renderSheet();
      break;
    }
    case 'ui_partial': {
      if (d.component === 'suggestions') break; // chips are not cards
      const slot = slotFor(turn, d.component, d.stream_id);
      if (slot && !slot.dataset.final) slot.innerHTML = UI.cardSkeleton(d.component);
      scrollBottom();
      break;
    }
    case 'ui': {
      if (d.component === 'suggestions') {
        state.suggestions = (d.payload?.suggestions || []).slice(0, 4);
        const nodes = turnDom.get(turn.id);
        if (nodes) [...nodes.slots.values()].forEach((s) => {
          if (s.dataset.slotComponent === 'suggestions' && !s.dataset.final) s.remove();
        });
        renderSuggestions();
        break;
      }
      const slot = slotFor(turn, d.component, d.stream_id);
      turn.cards.push(d.component);
      if (slot) {
        slot.dataset.final = '1';
        slot.innerHTML = UI.renderCard(d.component, d.payload || {}, api);
        hydrateIcons(slot);
        // The card grows as its layout/images settle; re-pin to the bottom after paint.
        requestAnimationFrame(() => scrollBottom(false));
      }
      if (d.component === 'checkout') { state.checkoutStaged = true; renderCart(); }
      scrollBottom();
      break;
    }
    case 'cart_update':
      if (d.cart) {
        state.cart = d.cart;
        renderCart(); renderHeader();
        els.cartTopCount.classList.remove('pop');
        void els.cartTopCount.offsetWidth;
        els.cartTopCount.classList.add('pop');
      }
      break;
    case 'turn_complete':
      turn.usage = d.usage || null;
      turn.elapsed_ms = d.elapsed_ms || 0;
      turn.streaming = false;
      break;
    case 'error':
      turn.error = d.message || 'Something went wrong on our side. Please try again.';
      turn.streaming = false;
      break;
    default:
      break; // change_update and any future events are ignored by the storefront too
  }
}
function finishTurn(turn) {
  turn.streaming = false;
  const nodes = turnDom.get(turn.id);
  if (nodes) {
    nodes.activity.hidden = true;
    nodes.text.innerHTML = UI.markdown(turn.text);
    nodes.text.classList.remove('streaming-caret');
    if (turn.error) { nodes.error.hidden = false; nodes.error.textContent = turn.error; }
  }
  state.streaming = false;
  controller = null;
  renderHeader(); renderComposer(); renderSuggestions();
  scrollBottom(false);
  setTimeout(() => scrollBottom(false), 300);
  if (state.sheet === 'activity') renderSheet();
  void refreshCart();
  clearTimeout(memoryTimer);
  memoryTimer = setTimeout(() => { void refreshMemory(true); }, 2500);
}

async function send(message) {
  const text = String(message || '').trim();
  if (!text || state.streaming) return;
  if (!state.connected) { toast('Not connected to the shop API. Check Settings.'); return; }
  if (state.view !== 'assistant') setView('assistant');
  els.input.value = '';
  const turn = startTurn(text);
  state.streaming = true;
  controller = new AbortController();
  renderHeader(); renderComposer(); renderSuggestions();
  try {
    for await (const ev of api.chatStream(text, controller.signal)) {
      handleEvent(turn, ev);
      if (!turn.streaming && ev.type === 'turn_complete') break;
    }
  } catch (err) {
    if (err?.name === 'AbortError') {
      turn.text += (turn.text ? '\n\n' : '') + '_Stopped._';
    } else {
      turn.error = `Couldn't complete this request: ${err.message || err}`;
      setBanner(`Chat request failed: ${err.message || err}`);
    }
  }
  finishTurn(turn);
  els.input.focus();
}
function stopGenerating() {
  if (controller) controller.abort();
}

/* ---------------- actions ---------------- */
async function addProduct(productId) {
  try {
    const res = await api.addToCart(productId, 1);
    if (res?.cart) state.cart = res.cart;
    await refreshCart();
    renderHeader();
    toast('Added to cart');
  } catch (err) {
    toast(`Not added: ${err.message || err}`);
  }
}
async function showProduct(id) {
  openModal('<div class="card-skeleton"><div class="shimmer" style="width:60%"></div><div class="shimmer" style="width:90%"></div><div class="shimmer" style="width:40%;height:120px"></div></div>');
  try {
    const p = await api.getProduct(id);
    if (!p || !p.product_id) throw new Error('Product not found');
    openModal(UI.renderProductDetail(p, api));
  } catch (err) {
    openModal(`<p class="error-bubble">Couldn't load this product: ${UI.esc(err.message || err)}</p>`);
  }
}
function qtyChange(productId, delta, title) {
  const line = (state.cart.items || []).find((i) => i.product_id === productId);
  const next = (line?.quantity || 0) + Number(delta);
  const name = title || line?.title || 'item';
  if (next <= 0) void send(`Remove the ${name} from my cart.`);
  else void send(`Change the ${name} quantity to ${next}.`);
}
async function onAction(action, el) {
  switch (action) {
    case 'ask': void send(el.dataset.prompt); break;
    case 'add': void addProduct(el.dataset.id); break;
    case 'product': void showProduct(el.dataset.id); break;
    case 'open-url': openExternal(el.dataset.url); break;
    case 'view': setView(el.dataset.view); break;
    case 'order-filter': state.orderFilter = el.dataset.filter; renderOrders(); break;
    case 'qty': qtyChange(el.dataset.id, el.dataset.delta); break;
    case 'remove': void send(`Remove the ${el.dataset.title} from my cart.`); break;
    case 'checkout':
      if (state.checkoutStaged) {
        setView('assistant');
        const card = els.transcript.querySelector('[data-checkout-card]');
        if (card) card.scrollIntoView({ behavior: 'smooth', block: 'center' });
      } else void send('Check out my cart.');
      break;
    case 'reply-prev': state.activityIndex = Math.max(0, state.activityIndex - 1); renderSheet(); break;
    case 'reply-next': state.activityIndex = Math.min(state.turns.length - 1, state.activityIndex + 1); renderSheet(); break;
    case 'fact-edit': {
      const row = el.closest('.fact-row');
      const box = row.querySelector('.fact-editor');
      const fact = state.memory.find((f) => f.key === el.dataset.key);
      box.innerHTML = UI.renderFactEditor(fact?.value || '');
      box.hidden = false;
      box.querySelector('textarea').focus();
      break;
    }
    case 'fact-cancel': {
      const box = el.closest('.fact-row').querySelector('.fact-editor');
      box.hidden = true; box.innerHTML = '';
      break;
    }
    case 'fact-save': {
      const row = el.closest('.fact-row');
      const value = row.querySelector('textarea').value.trim();
      if (!value) { toast('A fact cannot be empty.'); return; }
      const fact = await api.patchMemory(row.dataset.key, value);
      if (!fact) { toast('The store refused that value.'); return; }
      await refreshMemory(true);
      toast('Saved');
      break;
    }
    case 'fact-forget': {
      const ok = await api.deleteMemory(el.dataset.key);
      if (!ok) { toast('Could not forget that fact.'); return; }
      await refreshMemory(false);
      toast('Forgotten');
      break;
    }
    case 'save-base': {
      // The WebView is served under the shop's own HTTPS origin. A different base would be
      // cross-origin (and possibly mixed content), so refuse it instead of failing silently.
      const input = $('api-base');
      const next = input.value.trim().replace(/\/+$/, '');
      if (next !== DEFAULT_BASE) {
        toast('This build is pinned to https://shop.mimi.money.');
        return;
      }
      await saveBase(next);
      await clearSession();
      state.base = next; api.setBase(next);
      state.connected = false;
      closeSheet();
      setBanner('');
      void boot();
      break;
    }
    case 'reset-session': {
      await api.reset({});
      state.sessionId = api.session;
      state.checkoutStaged = false;
      await Promise.all([refreshCart(), refreshMemory(false)]);
      toast('Session reset');
      renderSheet();
      break;
    }
    case 'clear-chat': {
      state.turns = []; turnDom.clear(); state.suggestions = []; state.checkoutStaged = false;
      els.transcript.innerHTML = '';
      renderHomeOrTranscript(); renderSuggestions(); renderCart();
      toast('Conversation cleared');
      break;
    }
    default: break;
  }
}

/* ---------------- events ---------------- */
function bindEvents() {
  document.addEventListener('click', (e) => {
    const el = e.target.closest('[data-action]');
    if (!el) return;
    if (el.disabled) return;
    const action = el.dataset.action;
    if (action === 'open-url' && el.tagName === 'A') return; // let real anchors work
    e.preventDefault();
    void onAction(action, el);
  });

  // Broken product photos fall back to the gradient placeholder underneath.
  document.addEventListener('error', (e) => {
    if (e.target instanceof HTMLImageElement) e.target.style.display = 'none';
  }, true);

  document.querySelectorAll('.view-btn').forEach((b) => {
    b.addEventListener('click', () => setView(b.dataset.view));
  });
  $('activity-btn').addEventListener('click', () => openSheet('activity'));
  $('account-btn').addEventListener('click', () => openSheet('account'));
  $('settings-btn').addEventListener('click', () => openSheet('settings'));
  els.statusPill.addEventListener('click', () => openSheet('settings'));
  $('sheet-close').addEventListener('click', closeSheet);
  els.scrim.addEventListener('click', () => { closeSheet(); closeModal(); });
  $('modal-close').addEventListener('click', closeModal);
  els.modal.addEventListener('click', (e) => { if (e.target === els.modal) closeModal(); });
  els.cartToggle.addEventListener('click', () => { state.cartOpen = !state.cartOpen; renderCart(); });
  $('connection-retry').addEventListener('click', () => { setBanner(''); void boot(); });
  $('connection-settings').addEventListener('click', () => openSheet('settings'));

  els.input.addEventListener('input', () => {
    els.input.style.height = 'auto';
    els.input.style.height = `${Math.min(160, els.input.scrollHeight)}px`;
    renderComposer();
  });
  els.input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      void send(els.input.value);
    }
  });
  els.send.addEventListener('click', () => void send(els.input.value));
  els.stop.addEventListener('click', stopGenerating);
  els.voice.addEventListener('click', toggleVoice);

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if (state.modalOpen) closeModal();
      else if (state.sheet) closeSheet();
    }
  });
  window.addEventListener('focus', () => { if (state.connected) void refreshCart(); });
}

function toggleVoice() {
  if (!voiceSupported) { toast('Voice input is not available in this browser.'); return; }
  if (listening) { recognition?.stop(); return; }
  const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Ctor) { voiceSupported = false; renderComposer(); toast('Voice input is not available in this browser.'); return; }
  try {
    recognition = new Ctor();
    recognition.lang = 'en-US';
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;
    const base = els.input.value;
    recognition.onresult = (event) => {
      let finalText = '';
      let interim = '';
      for (let i = 0; i < event.results.length; i++) {
        const r = event.results[i];
        if (r.isFinal) finalText += r[0].transcript;
        else interim += r[0].transcript;
      }
      els.input.value = `${base}${base && !base.endsWith(' ') ? ' ' : ''}${finalText}${interim}`.trimStart();
      els.input.dispatchEvent(new Event('input'));
    };
    recognition.onerror = (event) => {
      const copy = {
        'no-speech': "Didn't catch that — try again.", 'audio-capture': 'No microphone found.',
        'not-allowed': 'Microphone permission was denied.', 'service-not-allowed': 'Speech service unavailable.',
        network: 'Speech service needs a network connection.', language: 'Only English is supported.',
      };
      els.hint.hidden = false;
      els.hint.textContent = copy[event.error] || `Voice input error: ${event.error}`;
      setTimeout(() => { els.hint.hidden = true; }, 4000);
    };
    recognition.onstart = () => {
      listening = true; els.hint.hidden = false; els.hint.textContent = 'Listening… speak in English';
      renderComposer();
    };
    recognition.onend = () => {
      listening = false; els.hint.hidden = true; recognition = null; renderComposer(); els.input.focus();
    };
    recognition.start();
  } catch {
    voiceSupported = false; renderComposer(); toast('Voice input could not start.');
  }
}

/* ---------------- go ---------------- */
bindEvents();
hydrateIcons();
setView('assistant');
// Paint the shell immediately; boot() replaces the placeholders with live data.
renderHomeOrTranscript();
renderCart();
renderComposer();
void boot();

// Exposed for the browser test harness (read-only diagnostics).
window.__acme = {
  state,
  api,
  send: (m) => send(m),
  openSheet,
  setView,
  refreshCart,
  renderCart,
  renderAll,
  showProduct,
  snapshot: () => ({
    connected: state.connected,
    base: state.base,
    sessionId: state.sessionId,
    shopper: state.shopper,
    health: state.health,
    catalogCount: state.catalog.length,
    cart: state.cart,
    orderCount: (state.orders || []).length,
    memoryCount: state.memory.length,
    view: state.view,
    turns: state.turns.map((t) => ({
      user: t.user, textLength: t.text.length, streaming: t.streaming, error: t.error,
      cards: t.cards, steps: t.steps.map((s) => ({ tool: s.tool, status: s.status })),
      usage: t.usage,
    })),
    renderedCards: [...document.querySelectorAll('[data-component]')].map((c) => c.dataset.component),
    suggestions: state.suggestions,
    streaming: state.streaming,
  }),
};
