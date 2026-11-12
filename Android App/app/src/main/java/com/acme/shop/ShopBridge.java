// Copyright 2026 — ACME Shop Android client.
// The JavascriptInterface surface exposed to the bundled shop client.
package com.acme.shop;

import android.util.Log;
import android.webkit.JavascriptInterface;
import android.widget.Toast;

import org.json.JSONObject;

public final class ShopBridge {
    private static final String TAG = "AcmeShop";
    private final MainActivity activity;

    ShopBridge(MainActivity activity) {
        this.activity = activity;
    }

    /** PayPal approval / tracking links open in the user's browser, not inside the WebView. */
    @JavascriptInterface
    public void openExternal(String url) {
        if (url == null) return;
        if (!url.startsWith("https://") && !url.startsWith("http://")) return;
        activity.runOnUiThread(() -> activity.openExternal(url));
    }

    /** Native Android speech recognition (WebView has no Web Speech API). */
    @JavascriptInterface
    public void startVoice(String lang) {
        activity.runOnUiThread(() -> activity.startVoice(lang));
    }

    @JavascriptInterface
    public void stopVoice() {
        activity.runOnUiThread(() -> activity.stopVoice());
    }

    @JavascriptInterface
    public void toast(String message) {
        activity.runOnUiThread(() ->
                Toast.makeText(activity, message == null ? "" : message, Toast.LENGTH_SHORT).show());
    }

    /** The web client reports whether the shop API answered, for the native status chip. */
    @JavascriptInterface
    public void setOnline(boolean online) {
        activity.runOnUiThread(() -> activity.setOnline(online));
    }

    @JavascriptInterface
    public void log(String message) {
        Log.d(TAG, "WEB: " + (message == null ? "" : message));
    }

    @JavascriptInterface
    public String appInfo() {
        try {
            JSONObject o = new JSONObject();
            o.put("name", "ACME Shop");
            o.put("version", "1.0.0");
            o.put("platform", "Android");
            o.put("upstream", "https://shop.mimi.money");
            return o.toString();
        } catch (Exception e) {
            return "{}";
        }
    }
}
