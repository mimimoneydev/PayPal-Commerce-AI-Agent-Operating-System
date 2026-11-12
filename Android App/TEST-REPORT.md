# ACME Shop Android — Emulator Test Report

**Verdict: PASS.** 18 / 18 automated checks passed on two consecutive clean runs
(2026-11-11 18:15 and 18:16 local, GMT+3). No uncaught JavaScript exceptions, no HTTP
4xx/5xx from the app, no native crashes, and no console errors other than the ones
deliberately caused by the offline test.

> Scope note: the `Android App/` folder already existed as an in-progress build. This
> work continued that build — completed it, rebuilt the APK, fixed the issues found,
> ran the emulator verification and produces this report.

---

## 1. Environment

| Item | Value |
| --- | --- |
| Host | macOS (darwin), Apple Silicon |
| Emulator | Android Emulator 36.6.11.0, AVD `Pixel_9_Pro`, headless (`-no-window`) |
| Device image | `sdk_gphone16k_arm64`, Android 17, API 37 (`google_apis_playstore_ps16k`, arm64-v8a, 16 KB pages) |
| Display | 1280 × 2856, 480 dpi |
| Android SDK | build-tools 35.0.0, platform android-35, platform-tools/adb |
| JDK | OpenJDK 17.0.19 (Temurin) |
| Test runtime | Node.js 22.22.2 (built-in WebSocket, no npm dependencies) |
| App | `com.acme.shop` 1.0.0, minSdk 26, targetSdk 35, debug-signed v2 + v3, 65 KB |
| Live shop | `https://shop.mimi.money` — 87 products, 5 orders, 5–6 memory facts, model `deepseek/deepseek-v4.1-flash`, payments `paypal` |
| Network | Emulator reached the shop directly over HTTPS (TCP 443 probe passed); no proxy needed |

Build verification: `./build.sh` completed all 7 stages (aapt2 compile/link, javac,
d8, zipalign, apksigner); `apksigner verify` reported **v2: true, v3: true**, one signer
(`CN=Android Debug`). `adb install -r` succeeded.

## 2. Method

1. Boot the AVD, install and launch the APK.
2. Forward the WebView DevTools socket (`webview_devtools_remote_<pid>`) to `tcp:9222`.
3. `tests/emulator-test.mjs` attaches over CDP, enables `Runtime`, `Log`, `Network`,
   `Page`, reloads for a deterministic start, then drives real DOM clicks and the
   app's own `__acme` diagnostics surface. It records console errors, uncaught
   exceptions, failed requests and HTTP ≥ 400 responses throughout.
4. Full-device screenshots via `adb exec-out screencap -p`; native interactions
   (Back, header buttons) via `adb shell input`; native crashes checked via `logcat`.
5. Results to `tests/results.json`, screenshots to `screenshots/`.

The harness talks to the **live shop API** — no mocks, no stubbed chat stream.

## 3. Results

| # | Check | Result | Observed |
| --- | --- | --- | --- |
| T01 | Boot on shop origin with live data | PASS | 87 products, 5 orders, 5–6 facts, shopper Priya, session id issued |
| T02 | Native shell + Android shim | PASS | 7 bundled assets served under `https://shop.mimi.money`, `AndroidShop` bridge + voice shim present |
| T03 | Assistant SSE turn | PASS | `products` card, 4 tool steps, 3 follow-up suggestions, streamed text |
| T04 | Product detail modal | PASS | `GET /api/products/{id}` → title, $79.00, rating, description; modal opens/closes |
| T05 | Add to cart (provenance gate) | PASS | item_count 0 → 1, subtotal $79 USD |
| T06 | Cart panel + quantity stepper | PASS | 2 qty controls; stepper drove an agent turn, item_count 1 → 2 |
| T07 | Checkout card + PayPal handoff | PASS | "Ready to check out", **Not charged**, line items, subtotal/shipping/tax, estimated total, `Pay securely with PayPal` → `/api/payments/paypal/checkout/<token>` |
| T08 | Orders view | PASS | 5 orders, filters All / On the way / Delayed / Past, delayed filter applied |
| T09 | Activity / tool trace | PASS | Per-turn steps with tool names, status and elapsed time |
| T10 | Memory edit round-trip | PASS | First fact (`camping_experience`) PATCHed then restored to its original value |
| T11 | Settings + session reset | PASS | Correct base URL and host status; `POST /api/reset` issued a new session, cart cleared |
| T12 | Suggestion chip | PASS | Chip started a new streaming turn that completed with prose reply |
| T13 | Voice shim | PASS | Native recognizer success and `no-speech` error paths delivered into the page |
| T14 | Hardware Back | PASS | Back closed the open sheet; `MainActivity` stayed resumed |
| T15 | Native header buttons | PASS | Settings and Cart header buttons drove the WebView |
| T16 | Offline / reconnect | PASS | Offline banner ("Couldn't reach the shop API … Failed to fetch") + native OFFLINE dot; Retry restored LIVE |
| T17 | Final state | PASS | Still connected, 87 products, 5 orders, 4 chat turns; no `FATAL EXCEPTION` in logcat |
| T18 | Diagnostics | PASS | 0 uncaught exceptions, 0 app console errors, 0 HTTP ≥ 400 |

**Additional manual checks (outside the 18):**

- Native **Reload** header button reloaded the WebView (a JS marker was cleared) and
  reconnected to the API automatically.
- `AndroidShop.openExternal(...)` handed a URL to the system browser
  (`topResumedActivity=com.android.chrome/...`) — this is the path the PayPal approval
  link uses.

## 4. Findings and fixes

| # | Finding | Resolution |
| --- | --- | --- |
| 1 | Emulator refused to boot: *"A snapshot operation for Pixel_9_Pro is pending and timeout has expired"* | Removed the specific stale `*.lock`/`snapshot.*` files left by an earlier crashed session; booted with `-no-snapshot`. No user data touched. |
| 2 | First checkout test failed: the assistant replied *"Checkout staging is temporarily unavailable"* instead of rendering a card | **Not an app defect.** The test cart was $395, above the host's `COMMERCE_MAX_ORDER_AMOUNT=250.00` ceiling (`PayPal-Commerce-AI-Agent-OS/.env.example`). The server's shopping-agent executor raises, and returns its generic "tool temporarily unavailable" wording. The app surfaced the tool error in the Activity sheet and in the assistant's reply with no crash, no card and no charge — the web portal behaves the same. Re-tested with a $79 / $158 cart: the checkout card and PayPal handoff rendered correctly. The harness now keeps carts under the cap. |
| 3 | Settings sheet still had Chrome-extension copy and a "Save & reconnect" button that could silently break on a different origin | Rewrote the copy for Android, made the base URL read-only, renamed the action to **Reconnect**, and made it refuse any base other than the shop origin (a different base would be cross-origin/mixed-content from this page). Verified in run 2+. |
| 4 | Hosted LLM occasionally ends a turn after tool calls with no text and no card (the web portal does too), and sometimes returns out-of-stock products | Harness now rephrases a search up to 3 times until a product card appears, and clicks only *enabled* Add buttons. This is test robustness, not an app change. |
| 5 | Extension-era header comments in `app.js`, `api.js`, `styles.css` | Updated to describe the Android/origin-interception architecture. |

Diagnostics from the final run: `exceptions: 0`, `badResponses: 0`,
`consoleErrors: 2` and `failedRequests: 1` — all `net::ERR_INTERNET_DISCONNECTED`
from T16's deliberate offline emulation, excluded by T18.

## 5. Screenshots

Captured on the emulator during the final passing run (`screenshots/`):

| File | Shows |
| --- | --- |
| `01-home.png` | Home: greeting, 4 orders on the way, starter prompts, arriving orders, popular products |
| `02-assistant-products.png` | Streamed assistant reply with product card and suggestion chips |
| `03-product-detail.png` | Product detail modal |
| `04-cart.png` | Cart panel with lines, totals and quantity controls |
| `05-checkout.png` | Checkout card, "Not charged", PayPal handoff button |
| `06-orders.png` | Orders view with filters and status chips |
| `07-memory.png` | Profile & memory sheet |
| `08-settings.png` | Settings / host status / session controls |
| `09-offline.png` | Offline banner and native OFFLINE indicator |
| `10-final-state.png` | Final connected state |

## 6. Not tested / limitations

- **No real PayPal approval or capture.** Checkout was staged only; the approval URL
  was never opened and no payment was authorised. Creating the staged card does create
  a sandbox order draft on the host, but nothing is charged.
- **No real microphone speech.** The emulator has no speech service; the shim's
  success and error paths were exercised programmatically.
- The shop requires a network connection; only the UI is bundled offline.
- Demo data is shared across clients; the harness resets the session, restores the
  one memory fact it edits, and leaves no lasting change.
- The APK is debug-signed — suitable for sideloading/emulator, not Play Store release.

## 7. Reproduce

```bash
cd "Android App"
./tests/run-tests.sh
# or, with an emulator already running and the APK installed:
adb forward tcp:9222 localabstract:webview_devtools_remote_<pid>
node tests/emulator-test.mjs
```

## 8. Conclusion

The Android app delivers the full `shop.mimi.money` experience — assistant chat with
streaming tool activity, catalog and product cards, cart, cap-bounded staged PayPal
checkout, orders, memory, activity inspection, settings, voice, offline recovery and
native Android navigation — against the same live API and with the same server-side
safety gates as the web portal. Installing the APK is sufficient; no URL is needed.
The emulator verification is clean: **18/18 checks passed twice, zero app errors.**
