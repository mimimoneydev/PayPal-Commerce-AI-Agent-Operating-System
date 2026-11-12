// Copyright 2026 — ACME Shop Android client.
//
// A native Android shell around the full ACME storefront client. The UI is bundled in
// assets/ and served by shouldInterceptRequest under the shop's own HTTPS origin, so the
// page is same-origin with /api/ — exactly like the deployed Next.js storefront behind
// nginx. That means the SSE chat stream, JSON POSTs and X-Session-Id work with no CORS
// bridge, and the server-side provenance/cap/approval gates are untouched.
package com.acme.shop;

import android.Manifest;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.NetworkRequest;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.ConsoleMessage;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.Map;

public class MainActivity extends Activity {
    private static final String TAG = "AcmeShop";
    private static final String HOST = "shop.mimi.money";
    private static final String APP_PREFIX = "/__acme_app__/";
    private static final String APP_URL = "https://" + HOST + APP_PREFIX + "index.html";
    private static final int REQ_AUDIO = 2001;

    private WebView web;
    private LinearLayout headerView;
    private TextView statusLabel;
    private View statusDot;
    private ShopBridge bridge;
    private SpeechRecognizer recognizer;
    private String pendingVoiceLang;
    private ConnectivityManager connectivity;
    private ConnectivityManager.NetworkCallback networkCallback;
    private boolean pageLoaded = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        getWindow().setStatusBarColor(Color.parseColor("#1E2C4F"));
        getWindow().setNavigationBarColor(Color.WHITE);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.parseColor("#F4F6FA"));
        headerView = buildHeader();
        root.addView(headerView, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        applySystemInsets(root);

        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor("#F4F6FA"));
        root.addView(web, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        setContentView(root);

        WebView.setWebContentsDebuggingEnabled(true);
        configureWebView();
        bridge = new ShopBridge(this);
        web.addJavascriptInterface(bridge, "AndroidShop");

        monitorConnectivity();
        web.loadUrl(APP_URL);
    }

    /* ---------------- native header ---------------- */

    private LinearLayout buildHeader() {
        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setBackgroundColor(Color.parseColor("#1E2C4F"));
        int pad = dp(12);
        bar.setPadding(pad, dp(10), dp(8), dp(10));

        TextView tile = new TextView(this);
        tile.setText("A");
        tile.setTextColor(Color.parseColor("#1E2C4F"));
        tile.setTypeface(Typeface.DEFAULT_BOLD);
        tile.setTextSize(16);
        tile.setGravity(Gravity.CENTER);
        GradientDrawable tileBg = new GradientDrawable();
        tileBg.setColor(Color.WHITE);
        tileBg.setCornerRadius(dp(8));
        tile.setBackground(tileBg);
        int tileSize = dp(32);
        bar.addView(tile, new LinearLayout.LayoutParams(tileSize, tileSize));

        LinearLayout titles = new LinearLayout(this);
        titles.setOrientation(LinearLayout.VERTICAL);
        titles.setPadding(dp(10), 0, 0, 0);
        TextView name = new TextView(this);
        name.setText(getString(R.string.app_name));
        name.setTextColor(Color.WHITE);
        name.setTypeface(Typeface.DEFAULT_BOLD);
        name.setTextSize(15);
        titles.addView(name);
        TextView sub = new TextView(this);
        sub.setText(getString(R.string.app_subtitle));
        sub.setTextColor(Color.parseColor("#C9D2E6"));
        sub.setTextSize(9);
        titles.addView(sub);
        bar.addView(titles, new LinearLayout.LayoutParams(0,
                ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        LinearLayout status = new LinearLayout(this);
        status.setOrientation(LinearLayout.HORIZONTAL);
        status.setGravity(Gravity.CENTER_VERTICAL);
        statusDot = new View(this);
        GradientDrawable dot = new GradientDrawable();
        dot.setShape(GradientDrawable.OVAL);
        dot.setColor(Color.parseColor("#FFC46B"));
        statusDot.setBackground(dot);
        status.addView(statusDot, new LinearLayout.LayoutParams(dp(7), dp(7)));
        statusLabel = new TextView(this);
        statusLabel.setText("CONNECTING");
        statusLabel.setTextColor(Color.parseColor("#FFC46B"));
        statusLabel.setTextSize(9);
        statusLabel.setTypeface(Typeface.DEFAULT_BOLD);
        statusLabel.setPadding(dp(5), 0, dp(6), 0);
        status.addView(statusLabel);
        bar.addView(status);

        bar.addView(makeHeaderButton("\u21bb", "Reload shop", v -> {
            if (web != null) web.reload();
        }));
        bar.addView(makeHeaderButton("\u2699", "Settings", v -> {
            if (web != null) web.evaluateJavascript(
                    "window.__acme && window.__acme.openSheet('settings')", null);
        }));
        bar.addView(makeHeaderButton("\u2630", "Cart", v -> {
            if (web != null) web.evaluateJavascript(
                    "document.getElementById('cart-toggle').click()", null);
        }));
        return bar;
    }

    private TextView makeHeaderButton(String glyph, String description, View.OnClickListener action) {
        TextView b = new TextView(this);
        b.setText(glyph);
        b.setContentDescription(description);
        b.setTextColor(Color.WHITE);
        b.setTextSize(19);
        b.setGravity(Gravity.CENTER);
        b.setPadding(dp(6), dp(2), dp(6), dp(2));
        b.setMinimumWidth(dp(34));
        b.setOnClickListener(action);
        return b;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    /** Android 15 forces edge-to-edge for targetSdk 35: keep content clear of system bars. */
    private void applySystemInsets(View root) {
        final int baseTop = dp(10);
        root.setOnApplyWindowInsetsListener((v, insets) -> {
            int top, bottom;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                android.graphics.Insets bars = insets.getInsets(
                        android.view.WindowInsets.Type.systemBars());
                top = bars.top;
                bottom = bars.bottom;
            } else {
                top = systemDimen("status_bar_height");
                bottom = systemDimen("navigation_bar_height");
            }
            headerView.setPadding(headerView.getPaddingLeft(), baseTop + top,
                    headerView.getPaddingRight(), baseTop);
            v.setPadding(0, 0, 0, bottom);
            return insets;
        });
        root.requestApplyInsets();
    }

    private int systemDimen(String name) {
        int id = getResources().getIdentifier(name, "dimen", "android");
        return id > 0 ? getResources().getDimensionPixelSize(id) : dp(24);
    }

    /* ---------------- WebView ---------------- */

    private void configureWebView() {
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setAllowFileAccess(true);
        s.setAllowContentAccess(true);
        s.setLoadWithOverviewMode(false);
        s.setUseWideViewPort(true);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setCacheMode(WebSettings.LOAD_NO_CACHE);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        s.setUserAgentString(s.getUserAgentString() + " ACME-Shop-Android/1.0");

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onConsoleMessage(ConsoleMessage cm) {
                Log.d(TAG, "console[" + cm.messageLevel() + "] " + cm.message()
                        + " (" + cm.sourceId() + ":" + cm.lineNumber() + ")");
                return true;
            }
        });

        web.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                return localAsset(request);
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri u = request.getUrl();
                if (u == null) return false;
                if (HOST.equals(u.getHost()) && u.getPath() != null
                        && u.getPath().startsWith(APP_PREFIX)) return false;
                if ("https".equals(u.getScheme()) || "http".equals(u.getScheme())) {
                    openExternal(u.toString());
                    return true;
                }
                return false;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                super.onPageFinished(view, url);
                if (url != null && url.startsWith("https://" + HOST + APP_PREFIX)) {
                    pageLoaded = true;
                    setOnline(isOnline());
                }
            }

            @Override
            public void onReceivedError(WebView view, int errorCode, String description, String failingUrl) {
                super.onReceivedError(view, errorCode, description, failingUrl);
                if (failingUrl != null && failingUrl.startsWith("https://" + HOST + APP_PREFIX)) {
                    Log.e(TAG, "main document error " + errorCode + ": " + description);
                    setOnline(false);
                    Toast.makeText(MainActivity.this,
                            "Couldn't load the shop UI: " + description, Toast.LENGTH_LONG).show();
                }
            }
        });
    }

    /** Serve the bundled client under the shop origin; everything else hits the live host. */
    private WebResourceResponse localAsset(WebResourceRequest request) {
        Uri u = request.getUrl();
        if (u == null || !HOST.equals(u.getHost())) return null;
        String path = u.getPath();
        if (path == null || !path.startsWith(APP_PREFIX)) return null;
        String name = path.substring(APP_PREFIX.length());
        if (name.isEmpty()) name = "index.html";
        if (name.contains("..") || name.startsWith("/")) return null;
        try {
            InputStream in = getAssets().open(name);
            Map<String, String> headers = new HashMap<>();
            headers.put("Cache-Control", "no-store, no-cache, must-revalidate");
            headers.put("Access-Control-Allow-Origin", "*");
            WebResourceResponse response = new WebResourceResponse(mimeOf(name), "UTF-8", in);
            response.setResponseHeaders(headers);
            return response;
        } catch (IOException e) {
            Log.e(TAG, "asset missing: " + name);
            return null;
        }
    }

    private static String mimeOf(String name) {
        String n = name.toLowerCase();
        if (n.endsWith(".html") || n.endsWith(".htm")) return "text/html";
        if (n.endsWith(".js") || n.endsWith(".mjs")) return "text/javascript";
        if (n.endsWith(".css")) return "text/css";
        if (n.endsWith(".json")) return "application/json";
        if (n.endsWith(".png")) return "image/png";
        if (n.endsWith(".webp")) return "image/webp";
        if (n.endsWith(".svg")) return "image/svg+xml";
        if (n.endsWith(".ico")) return "image/x-icon";
        return "application/octet-stream";
    }

    /* ---------------- native actions ---------------- */

    void openExternal(String url) {
        try {
            Intent i = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(i);
        } catch (Exception e) {
            Toast.makeText(this, "No browser available to open this link", Toast.LENGTH_SHORT).show();
        }
    }

    void setOnline(boolean online) {
        if (statusDot == null || statusLabel == null) return;
        GradientDrawable dot = new GradientDrawable();
        dot.setShape(GradientDrawable.OVAL);
        dot.setColor(Color.parseColor(online ? "#4ADE9B" : "#FFC46B"));
        statusDot.setBackground(dot);
        statusLabel.setText(online ? "LIVE" : "OFFLINE");
        statusLabel.setTextColor(Color.parseColor(online ? "#4ADE9B" : "#FFC46B"));
    }

    private boolean isOnline() {
        if (connectivity == null) return true;
        Network n = connectivity.getActiveNetwork();
        if (n == null) return false;
        NetworkCapabilities caps = connectivity.getNetworkCapabilities(n);
        return caps != null && caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET);
    }

    private void monitorConnectivity() {
        connectivity = (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
        if (connectivity == null) return;
        networkCallback = new ConnectivityManager.NetworkCallback() {
            @Override public void onAvailable(Network network) { runOnUiThread(() -> setOnline(true)); }
            @Override public void onLost(Network network) { runOnUiThread(() -> setOnline(false)); }
        };
        try {
            NetworkRequest req = new NetworkRequest.Builder()
                    .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET).build();
            connectivity.registerNetworkCallback(req, networkCallback);
        } catch (Exception e) {
            Log.w(TAG, "connectivity callback unavailable", e);
        }
        setOnline(isOnline());
    }

    /* ---------------- voice ---------------- */

    void startVoice(String lang) {
        final String language = (lang == null || lang.isEmpty()) ? "en-US" : lang;
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            pendingVoiceLang = language;
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQ_AUDIO);
            return;
        }
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            pushVoice(null, "service-not-allowed");
            return;
        }
        if (recognizer != null) {
            recognizer.destroy();
            recognizer = null;
        }
        recognizer = SpeechRecognizer.createSpeechRecognizer(this);
        recognizer.setRecognitionListener(new RecognitionListener() {
            @Override public void onReadyForSpeech(Bundle params) { }
            @Override public void onBeginningOfSpeech() { }
            @Override public void onRmsChanged(float rmsdB) { }
            @Override public void onBufferReceived(byte[] buffer) { }
            @Override public void onEndOfSpeech() { }
            @Override public void onPartialResults(Bundle partialResults) { }
            @Override public void onEvent(int eventType, Bundle params) { }
            @Override
            public void onResults(Bundle results) {
                ArrayList<String> matches = results == null ? null
                        : results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                pushVoice(matches != null && !matches.isEmpty() ? matches.get(0) : null,
                        matches != null && !matches.isEmpty() ? null : "no-speech");
            }
            @Override
            public void onError(int error) {
                String code;
                switch (error) {
                    case SpeechRecognizer.ERROR_NO_MATCH:
                    case SpeechRecognizer.ERROR_SPEECH_TIMEOUT: code = "no-speech"; break;
                    case SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS: code = "not-allowed"; break;
                    case SpeechRecognizer.ERROR_NETWORK:
                    case SpeechRecognizer.ERROR_NETWORK_TIMEOUT: code = "network"; break;
                    case SpeechRecognizer.ERROR_AUDIO: code = "audio-capture"; break;
                    default: code = "service-not-allowed";
                }
                pushVoice(null, code);
            }
        });
        Intent intent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, language);
        intent.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true);
        intent.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1);
        try {
            recognizer.startListening(intent);
        } catch (Exception e) {
            Log.w(TAG, "voice start failed", e);
            pushVoice(null, "service-not-allowed");
        }
    }

    void stopVoice() {
        if (recognizer != null) {
            try { recognizer.stopListening(); } catch (Exception ignored) { }
        }
    }

    private void pushVoice(String text, String error) {
        final String js = "window.__androidVoiceResult(" + jsonQuote(text) + ","
                + jsonQuote(error) + ")";
        runOnUiThread(() -> {
            if (web != null) web.evaluateJavascript(js, null);
        });
    }

    private static String jsonQuote(String value) {
        if (value == null) return "null";
        try {
            return JSONObject.quote(value);
        } catch (Exception e) {
            return "null";
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQ_AUDIO && pendingVoiceLang != null) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                String lang = pendingVoiceLang;
                pendingVoiceLang = null;
                startVoice(lang);
            } else {
                pendingVoiceLang = null;
                pushVoice(null, "not-allowed");
            }
        }
    }

    /* ---------------- back ---------------- */

    @Override
    public void onBackPressed() {
        if (web == null || !pageLoaded) {
            super.onBackPressed();
            return;
        }
        web.evaluateJavascript(
                "(function(){try{"
                        + "if(!document.getElementById('modal').hidden){document.getElementById('modal-close').click();return true;}"
                        + "if(!document.getElementById('sheet').hidden){document.getElementById('sheet-close').click();return true;}"
                        + "if(window.__acme.state.cartOpen && window.innerWidth<=1180){document.getElementById('cart-toggle').click();return true;}"
                        + "if(window.__acme.state.view!=='assistant'){window.__acme.setView('assistant');return true;}"
                        + "return false;}catch(e){return false;}})()",
                value -> {
                    if (!"true".equals(value)) finish();
                });
    }

    @Override
    protected void onDestroy() {
        if (recognizer != null) {
            recognizer.destroy();
            recognizer = null;
        }
        if (connectivity != null && networkCallback != null) {
            try { connectivity.unregisterNetworkCallback(networkCallback); } catch (Exception ignored) { }
        }
        if (web != null) web.destroy();
        super.onDestroy();
    }
}
