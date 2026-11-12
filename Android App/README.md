# ACME Shop — Android app

A native Android client for the **PayPal Commerce AI Agent OS** storefront at
<https://shop.mimi.money>. Install the APK and you get the whole shop in an app —
no browser, no URL to type, no lost session. Every screen and action available in
the web portal is available here, backed by the same live `/api/` contract.

- **Package:** `com.acme.shop` · **Version:** 1.0.0 · **Min SDK:** 26 (Android 8.0) · **Target SDK:** 35
- **Deliverable:** [`apk/ACME-Shop.apk`](apk/ACME-Shop.apk) (debug-signed, ~65 KB)
- **Test report:** [`TEST-REPORT.md`](TEST-REPORT.md)

## What the app does

| Shop portal | Android app |
| --- | --- |
| AI Assistant with streamed replies | Same SSE stream (`POST /api/chat`), with live text, tool activity and stop-generation |
| Product search, picks, comparison, plans, guides | All 7 card renderers plus product-detail modal |
| Cart sidebar, quantity stepper, remove | Same cart with mobile layout; qty/remove go through the agent |
| "Ready to check out" card + PayPal handoff | Same card, "Not charged" disclosure, approval link opens in the device browser |
| Orders view with All / On the way / Delayed / Past filters | Same, with status chips and "Ask" shortcuts |
| Profile & memory (view / edit / forget facts) | Same, using `GET`/`PATCH`/`DELETE /api/memory` |
| Activity / Inspector sheet | Per-turn tool trace with timings and errors |
| Voice input (Web Speech API) | Native `android.speech.SpeechRecognizer` behind a Web Speech API shim |
| Suggestion chips, composer, Escape/back handling | Same, plus hardware Back closes sheets/modals before exiting |
| Connection/error banner, retry | Same, plus a native LIVE / OFFLINE indicator |
| — | Native header: reload, settings, cart; external links leave the WebView |

All server-side safety stays server-side: provenance gates before `cart/add`, the
`$250` spend ceiling, memory validation and the cap-bounded PayPal order are enforced
by the shop host. The app never holds a payment credential; PayPal approval happens
on PayPal's own page in the browser.

## How it is built

`MainActivity` creates a `WebView` and loads
`https://shop.mimi.money/__acme_app__/index.html`. There is no such path on the
server: `shouldInterceptRequest` serves the bundled files from `assets/` under that
HTTPS origin, and lets every other request (all `/api/...` calls, product images,
the PayPal link) go to the network. Because the page is **same-origin with `/api/`**,
the streaming chat, JSON POSTs and `X-Session-Id` header work exactly as they do
in the deployed Next.js storefront — no CORS proxy, no token handling in native code.

```
app/src/main/
├── java/com/acme/shop/
│   ├── MainActivity.java   WebView shell, asset interception, native header,
│   │                       network monitoring, speech recognizer, Back handling
│   └── ShopBridge.java     JavascriptInterface: openExternal / voice / toast / status
├── assets/                 Full storefront client (index.html, app.js, api.js, ui.js,
│                           styles.css, android.css, android-shim.js, icons/)
├── res/                    Launcher icons, colors, strings, theme, network security
└── AndroidManifest.xml
```

`android-shim.js` maps the small `chrome.*` surface the client was written against to
Android equivalents (`localStorage` for settings, `AndroidShop.openExternal` for
`tabs.create`) and replaces Web Speech with the platform recogniser.

## Build

Requires a local Android SDK (`build-tools/35.0.0`, `platforms/android-35`) and a JDK 11+.
No Gradle, Maven or network download is needed:

```bash
cd "Android App"
ANDROID_HOME="$HOME/Library/Android/sdk" ./build.sh
```

`build.sh` compiles resources (`aapt2`), Java (`javac`), dexes (`d8`), aligns and signs
with the bundled debug keystore. Gradle files are included so the project also opens
in Android Studio (`com.android.application` 8.13.2).

## Install

```bash
adb install -r apk/ACME-Shop.apk
adb shell am start -n com.acme.shop/.MainActivity
```

An internet connection is required — the shop's catalog, orders, memory and agent
live on the hosted API. The UI itself is bundled and loads instantly.

## Test

```bash
./tests/run-tests.sh            # boots the AVD, builds, installs, runs 18 CDP checks
```

See [`TEST-REPORT.md`](TEST-REPORT.md) for the recorded results, screenshots and
known caveats. The harness writes `tests/results.json` and refreshes `screenshots/`.

## Notes

- The build is pinned to `https://shop.mimi.money`. A different API base from a page
  served under that origin would be cross-origin (or mixed content), so Settings
  shows the base read-only and its button reconnects rather than silently failing.
- PayPal approval links intentionally open in the device browser, never inside the
  WebView, so the app never sees a payment page or credential.
- Voice input needs a device with a speech recognition service and `RECORD_AUDIO`.
  On an emulator the shim's success and error paths are testable but there is no mic.
- The demo shop uses shared sample data (Priya's cart, orders and memory). Tests
  reset the session and restore any memory fact they edit; they never approve a
  real payment.
