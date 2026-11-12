# Test report — ACME Shop Chrome extension

**Date:** 2026-11-11
**Verdict:** ✅ **PASS** — the unpacked extension loads in BrowserOS and delivers the full
shop functionality against the live `https://shop.mimi.money` API. Zero console errors and
zero network failures in the main functional run.

---

## 1. What was tested

An MV3 extension in this folder that replaces a visit to `https://shop.mimi.money` with a
click on the toolbar icon. It is a **real client of the live shop API**, not a mock: same
`X-Session-Id` session contract, same SSE chat stream, same cart/orders/memory endpoints and
the same server-side safety gates.

## 2. Test environment

| Item | Value |
|---|---|
| **Primary browser (requested)** | **BrowserOS 0.51.0** — `/Applications/BrowserOS.app/Contents/MacOS/BrowserOS` (Chromium **155.0.8309.26**) |
| Cross-check browser | Chrome for Testing 156.0.8078.4 (Playwright chromium-1248) |
| Launch flags | `--headless=new --no-sandbox --load-extension=<folder> --disable-extensions-except=<folder> --remote-debugging-port=<port> --proxy-server=<env proxy>` |
| Automation | Chrome DevTools Protocol over WebSocket (Node 22, no external npm packages) |
| Extension ID | `dhjecbmllnhokflahleacfmeghlimcbd` (pinned by the `key` in `manifest.json`) |
| Live backend | `https://shop.mimi.money` — health: `ok=true`, store `ACME`, **87 products**, model `deepseek/deepseek-v4.1-flash`, `payments: "paypal"`, 5 skills |
| Fixture data seen | 5 orders, 5 memory facts, shopper `Priya / ACME Subscription member` |

Each run used a fresh `--user-data-dir`, then CDP enabled `Runtime`, `Log`, `Page` and
`Network`, navigated to `chrome-extension://<id>/app.html`, executed scripted DOM
interactions, and collected console exceptions, failed requests, every shop API call and a
screenshot.

## 3. BrowserOS functional test — all passed

| # | Flow | Result |
|---|---|---|
| 1 | Boot / install | `connected=true`; 87 products, 5 orders, 5 memory facts loaded. Greeting, 4 starter prompts, 4 popular tiles rendered. Installing auto-opened the shop tab (service worker `onInstalled`). |
| 2 | Orders view | 5 rows, 4 filter segments, 8 status chips. `Delayed` → 2 rows, `Past` → 1 row, contextual Ask prompt `Where is order AR-79236 right now?` |
| 3 | View switching | Assistant ↔ Orders both work; composer placeholder changes per view. |
| 4 | Activity / Inspector sheet | Opens; step trace and token usage render. |
| 5 | Profile & memory sheet | 5 facts listed; Edit opens an inline textarea, Cancel closes it without writing. |
| 6 | Settings sheet | API base `https://shop.mimi.money`, 6 host-status rows (store, products, model, payments, skills, session). |
| 7 | **Streaming chat** | `Show me coffee makers under $150` → SSE turn with 5 tool steps, a `products` card, 1 product tile, 1 Add button, 3 suggestion chips, complete token usage (`11143 in / 1436 out / 16640 cache read`), `error=null`, streaming cleared. |
| 8 | **Add to cart from card** | Clicking Add on the surfaced `AR-1001` → `POST /api/cart/add` 200 → 1 cart line, `item_count=1`, subtotal `$79.00`, header badge `1`. |
| 9 | **Quantity stepper** | `+` → chat `Change the … quantity to 2.` → `cart_update` → `item_count=2`, first line `quantity=2`, subtotal `$158.00`. |
| 10 | **Checkout** | `Check out my cart.` → `checkout` UI card, cart lines, subtotal, free shipping, tax note, estimated total, returns line, **1 live PayPal handoff link**, `checkoutStaged=true`, cart footer switches to "View summary". |
| 11 | Activity trace | Per-reply stepping, 2 tool steps for the checkout reply, 2 expandable JSON blocks, correct token usage line. |
| 12 | Suggestion chips | Clicking a chip starts a real turn (`Delivery options to Maple Heights`), resolved via `get_fulfillment_options`. |
| 13 | Product detail modal | `GET /api/products/AR-1002` → title, price, out-of-stock chip, spec table, 90-day price-history sparkline, 3 review-aspect bars. |
| 14 | 4 chat turns total | All completed with `streaming=false`, `error=null`; final cart 2 items / `$158.00`. |

**Console errors: `[]` · Network failures: `[]`** for this run.

Observed API traffic: `GET /api/health`, `POST /api/session`, `GET /api/products?limit=100`,
`GET /api/cart`, `GET /api/orders`, `GET /api/memory`, `POST /api/chat` ×4,
`POST /api/cart/add`, `GET /api/products/AR-1002`, `/products/*.webp`, and the post-turn
cart/memory re-reads — all HTTP 200.

## 4. BrowserOS verification round — all passed

| # | Check | Result |
|---|---|---|
| 1 | Manifest / identity | `ACME Shop — PayPal Commerce AI Agent OS` v1.0.0, MV3, correct pinned ID, UA `HeadlessChrome/155.0.0.0`. |
| 2 | `PATCH /api/memory` round-trip | Edited the `workspace` fact, confirmed the new value, then **restored the original** — `changed=true, restored=true`. Shared demo data left unchanged. |
| 3 | `DELETE /api/memory` error path | Nonexistent key returns `false` with no exception (intentional 404). |
| 4 | Voice input | `SpeechRecognition` supported in BrowserOS, mic button enabled, clicking does not throw. |
| 5 | Bounded auto-buy receipt renderer | Synthetic payload → `data-payment-receipt` present, PayPal order id and authorised cap rendered, handoff link present. |
| 6 | All card renderers | `products`, `comparison`, `plan`, `guide`, `order_status`, `checkout`, `disclosure` — 7/7 render valid HTML. |
| 7 | Offline / bad host path | Pointing at an unreachable host is detected, the base URL and session are restored, no crash. |
| 8 | Service worker | `chrome.runtime.sendMessage({type:'open-shop'})` → `ok=true`, returned a tab id. |
| 9 | `POST /api/reset` | New session id, cart cleared to 0; `GET /api/health` still `ok=true` afterwards. |
| 10 | Checkout card fully in view | After the scroll fix, `checkoutVisible=true` (card fully inside the transcript viewport). |

The only console/network entries in this round were **two deliberately provoked, expected
ones**: a `404` from the nonexistent-key DELETE test, and `net::ERR_UNSAFE_PORT` from the
unreachable-host probe (`127.0.0.1:9`). Neither occurs in normal use.

## 5. Cross-origin / CORS verification

A plain cross-origin preflight from a non-extension origin to `/api/session` is rejected by
the FastAPI host (`400 Disallowed CORS origin`) — its allowlist only covers
`http://localhost:<port>`. With `host_permissions: ["https://shop.mimi.money/*"]`, Chrome
extension pages are exempt: CDNetwork events show **`GET`, `POST application/json` and
`X-Session-Id` requests going straight through with HTTP 200 and no preflight**. This was
confirmed in both BrowserOS and Chrome for Testing.

A safety gate was also observed working correctly: calling `POST /api/cart/add` for a
product that had **not** been returned by a catalog/order tool in that session is refused
with `400 "Product not in this session's results"`. The real user flow (search → Add)
succeeds. The extension surfaces the refusal as a toast.

## 6. Issues found and fixed during testing

| # | Issue | Fix |
|---|---|---|
| 1 | Card slots and cards both carried `data-component`, double-counting rendered cards | Slot attribute renamed to `data-slot-component` |
| 2 | `ui_partial` for `suggestions` could leave a shimmer skeleton card | Suggestion partials skipped; leftover skeletons removed on final `ui` |
| 3 | Image-less products showed letter initials instead of the portal's tinted glyph tiles | Ported the keyword/category glyph map and 8 tile colours from `lib/format.ts` |
| 4 | Blank page while the first API call was in flight | Shell (home/cart/composer) painted immediately, then replaced by live data on boot |
| 5 | Transcript sometimes stopped short of the bottom once a card grew | Re-pin scroll after paint and at turn completion — verified `checkoutVisible=true` |
| 6 | Settings could display a stale session id after reset/recovery | `api.onSession` callback keeps `state.sessionId` current |

## 7. Honest limitations

- **PayPal order creation was not executed live.** The checkout card and its real handoff
  link were verified against the hosted demo, and the bounded auto-buy receipt was verified
  with a synthetic payload, but no new PayPal sandbox order was created — that would write
  a new order to the shared public demo. Buyer approval and capture always happen on
  PayPal's own page, outside the extension.
- **Memory retraction on a real fact was not performed**, to avoid deleting shared demo data.
  The `PATCH` path was fully exercised and restored; `DELETE` was exercised on its error
  path, and the Forget button is wired to the same API method.
- **Voice dictation** needs a real microphone and user permission; headless BrowserOS
  could not grant it. The API is detected, the button is enabled, and clicking it is safe.
  Dictation only fills the composer — it never sends.
- The extension needs network access to the shop host. Offline it shows a connection banner
  and keeps the last good state; it does not ship an offline catalog or a local LLM.
- Custom API origins outside `shop.mimi.money` and local ports 8000 require adding them to
  `host_permissions` in `manifest.json` (noted in the Settings sheet).
- The hosted demo's session and memory are shared per `demo-user`; the extension persists
  its session token in `chrome.storage.local` (the web portal creates a fresh one on reload).

## 8. Evidence

| Screenshot | Shows |
|---|---|
| `screenshots/01-home.png` | BrowserOS home: greeting, brief, starters, Arriving, Popular shelf, cart panel, composer |
| `screenshots/02-assistant-and-product-detail.png` | Chat transcript, product card, checkout card, cart with 2 items, product detail modal with price history and review aspects |
| `screenshots/03-checkout.png` | Fully visible checkout summary with PayPal handoff, totals, suggestion chips, cart |
| `screenshots/04-live-shop-portal-reference.png` | The real `https://shop.mimi.money` portal for visual comparison |

## 9. Reproduce

```bash
# Load unpacked in BrowserOS and drive it with CDP (harness used for this report):
node /tmp/acme-test.mjs \
  "/Users/mike/Desktop/Hackathons/PayPal AI /code/paypal/Agentic Commerce/Chrome extension" \
  app.html 24000 "window.__acme.snapshot()" /tmp/acme-browseros-actions.json
# with BROWSER_BIN=/Applications/BrowserOS.app/Contents/MacOS/BrowserOS
#      EXT_ID=dhjecbmllnhokflahleacfmeghlimcbd
```

Or simply: open `chrome://extensions`, enable Developer mode, **Load unpacked** → this
folder, then click the **A** toolbar icon.
