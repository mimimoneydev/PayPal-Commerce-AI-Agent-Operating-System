# ACME Shop — Chrome extension

A full Manifest V3 client for the **PayPal Commerce AI Agent OS** retail storefront.
It gives you everything `https://shop.mimi.money` does, without opening the shop URL:
click the toolbar icon (or press `Alt+Shift+A`) and the complete shop opens in a tab
hosted by the extension itself.

There is no bundled copy of the catalog, no fake data and no second backend. The extension
calls exactly the same HTTP API the Next.js storefront calls, on the same origin, with the
same `X-Session-Id` session contract, the same SSE chat stream and the same safety gates.

## Install

1. Open `chrome://extensions` (Chromium, Chrome for Testing, Edge, Brave or **BrowserOS**).
2. Turn on **Developer mode** (top right).
3. Click **Load unpacked** and choose this `Chrome extension/` folder.
4. The shop tab opens automatically on install. Afterwards, click the **A** toolbar icon
   or press `Alt+Shift+A` to open/focus it.

The extension ID is pinned by the `key` in `manifest.json`, so it stays
`dhjecbmllnhokflahleacfmeghlimcbd` on every machine.

## What it does

| Surface | Parity with the shop portal |
|---|---|
| **Assistant / Home** | Date-aware greeting, order brief, 4 starter prompts, Arriving panel with Ask buttons, "Popular right now" shelf with product photos/glyphs |
| **Chat** | Streaming SSE turns (`text_delta`, `tool_call`, `tool_result`, `progress`, `ui_partial`, `ui`, `cart_update`, `turn_complete`, `error`), safe Markdown, activity line, streaming caret, suggestion chips, Stop button |
| **Generative cards** | `products` (carousel/grid/list), `comparison`, `plan`, `guide`, `order_status`, `checkout`, `disclosure`, plus `suggestions` as chips and an unknown-component fallback |
| **Product detail** | `GET /api/products/{id}` modal with price-history sparkline, review-aspect bars, specs, variants and Add button |
| **Cart** | Docked panel / drawer, quantity stepper, remove, free-shipping meter, subtotal, Check out, "Ask about this cart"; writes go through `POST /api/cart/add` and chat-driven `cart_update` events |
| **Orders** | All / On the way / Delayed / Past filters with counts, status pills, thumbnails, totals and contextual Ask prompts |
| **Checkout** | Cart summary, shipping/tax/estimated total, returns line, PayPal handoff link, and the cap-bounded auto-buy receipt (order id, authorised cap, amount, checkout id, immutable cart hash) |
| **Activity / Inspector** | Per-reply stepping, tool trace with input/result JSON, gate/error states, elapsed time and token usage |
| **Profile & memory** | `GET`/`PATCH`/`DELETE /api/memory` — list, edit inline, forget; "new this session" markers |
| **Composer** | Enter to send, Shift+Enter for newline, IME guard, Web Speech API voice dictation (`en-US`, never auto-sends), disabled when unsupported |
| **Settings** | Connection status, host health (store, products, model, payments, skills), editable API base URL, session reset, clear conversation |
| **Session** | `POST /api/session` + `X-Session-Id` on every scoped call, persisted in `chrome.storage.local`, auto-recovered on 401/409 |

### API contract used

```
POST   /api/session                  -> { session_id, user_id, name, tier }
POST   /api/chat                     -> SSE stream of AgentEvents
GET    /api/health
GET    /api/products?limit=100
GET    /api/products/{id}
GET    /api/cart
POST   /api/cart/add                 { product_id, quantity }
GET    /api/orders
GET    /api/memory
PATCH  /api/memory                   { key, value }
DELETE /api/memory                   { key }
POST   /api/reset                    { clear_memory, purge_memory }
GET    /products/{file}.webp
```

Chat is `POST`ed with `fetch()` and parsed line-by-line as `event:`/`data:` frames
(the hosted app does the same; `EventSource` cannot POST). The SSE frame shape is
`event: <type>\ndata: <one-line JSON>\n\n`.

### Why cross-origin works

`host_permissions` includes `https://shop.mimi.money/*`. Chrome/Chromium exempts
extension-page requests to hosts in that list from CORS, so a `chrome-extension://`
page can POST JSON with the `X-Session-Id` header without a preflight — even though
the FastAPI host only allows `http://localhost:<port>` origins for ordinary web pages.
No proxy, no content script and no hidden shop tab is needed. Permission is also
granted for `http://localhost:8000` and `http://127.0.0.1:8000` so
`python scripts/run_demo.py retail` works as a backend.

### Safety and privacy

The extension holds no payment credential. Prices, quantities and currency come from
the host; the provenance gate (products must have been returned by a catalog/order tool
in this session), spend cap and approval surface all stay on the server. PayPal approval
happens on PayPal's own page, opened in a normal tab from the checkout card's handoff
link. Only the session token and the API base URL are stored locally.

If the host is unreachable, the extension shows a connection banner and keeps the last
good state instead of crashing.

## Files

| File | Role |
|---|---|
| `manifest.json` | MV3 manifest, pinned key, permissions, action and keyboard shortcut |
| `background.js` | Service worker: opens/focuses the single shop tab on install and on action click |
| `app.html` / `styles.css` | Shell and the ACME design system (same tokens as `globals.css`) |
| `api.js` | HTTP + SSE client, session lifecycle, storage |
| `ui.js` | Pure HTML renderers: home, orders, cart, sheets, all generative cards, product detail |
| `app.js` | State, event stream handling, actions, voice, sheets, modal |
| `icons/` | 16/32/48/128 PNG toolbar icons |
| `TEST-REPORT.md` | BrowserOS test report |

## Local backend

To point at a local instance, open **Settings** in the extension and set the API base URL
to `http://localhost:8000`, then **Save & reconnect**. The backend must allow that Host
(`DEMO_ALLOWED_HOSTS`) as described in the repo's deployment docs.
