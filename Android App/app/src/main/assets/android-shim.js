/* Android shim — loaded before the shop client's ES module.
 * Maps the small chrome.* surface the client uses to Android-native equivalents and
 * replaces the Web Speech API (not available in WebView) with the platform recogniser.
 * No network code here: the page is served under https://shop.mimi.money/__acme_app__/
 * so /api/ is same-origin and fetch/SSE work exactly as they do in the browser.
 */
(function () {
  'use strict';
  document.documentElement.classList.add('android');
  window.__ANDROID__ = true;

  /* ---- chrome.storage.local over localStorage (JSON encoded) ---- */
  var storageLocal = {
    get: function (keys) {
      var out = {};
      var list = Array.isArray(keys) ? keys : [keys];
      for (var i = 0; i < list.length; i++) {
        var raw = null;
        try { raw = localStorage.getItem(list[i]); } catch (e) { /* storage disabled */ }
        if (raw !== null) {
          try { out[list[i]] = JSON.parse(raw); } catch (e) { out[list[i]] = raw; }
        }
      }
      return Promise.resolve(out);
    },
    set: function (obj) {
      Object.keys(obj || {}).forEach(function (k) {
        try { localStorage.setItem(k, JSON.stringify(obj[k])); } catch (e) { /* quota */ }
      });
      return Promise.resolve();
    },
    remove: function (key) {
      try { localStorage.removeItem(key); } catch (e) { /* ignore */ }
      return Promise.resolve();
    }
  };

  window.chrome = {
    storage: { local: storageLocal },
    tabs: {
      create: function (opts) {
        if (opts && opts.url && window.AndroidShop) AndroidShop.openExternal(opts.url);
        else if (opts && opts.url) window.open(opts.url, '_blank', 'noopener');
      }
    },
    runtime: {
      id: 'android',
      getManifest: function () { return { name: 'ACME Shop', version: '1.0.0' }; },
      sendMessage: function (_msg, cb) { if (cb) cb({ ok: true }); }
    }
  };

  /* ---- Web Speech API backed by android.speech.SpeechRecognizer ---- */
  function AndroidSpeechRecognition() {
    this.lang = 'en-US';
    this.continuous = false;
    this.interimResults = false;
    this.maxAlternatives = 1;
    this.onresult = null;
    this.onerror = null;
    this.onstart = null;
    this.onend = null;
  }
  AndroidSpeechRecognition.prototype.start = function () {
    window.__androidVoice = this;
    if (this.onstart) this.onstart({ type: 'start' });
    if (window.AndroidShop) AndroidShop.startVoice(this.lang || 'en-US');
    else window.__androidVoiceResult(null, 'service-not-allowed');
  };
  AndroidSpeechRecognition.prototype.stop = function () {
    if (window.AndroidShop) AndroidShop.stopVoice();
  };
  AndroidSpeechRecognition.prototype.abort = AndroidSpeechRecognition.prototype.stop;
  window.SpeechRecognition = AndroidSpeechRecognition;
  window.webkitSpeechRecognition = AndroidSpeechRecognition;

  window.__androidVoiceResult = function (text, error) {
    var recognition = window.__androidVoice;
    window.__androidVoice = null;
    if (!recognition) return;
    if (error) {
      if (recognition.onerror) recognition.onerror({ error: error });
    } else if (recognition.onresult) {
      var first = [{ transcript: String(text || ''), confidence: 1 }];
      first.isFinal = true;
      var results = [first];
      recognition.onresult({ results: results, resultIndex: 0 });
    }
    if (recognition.onend) recognition.onend({ type: 'end' });
  };

  /* ---- diagnostics used by the emulator test harness ---- */
  window.__androidInfo = function () {
    return {
      platform: 'Android',
      webView: navigator.userAgent,
      bridge: !!(window.AndroidShop),
      voice: typeof window.SpeechRecognition,
      origin: location.origin,
      appInfo: window.AndroidShop ? JSON.parse(AndroidShop.appInfo()) : null
    };
  };
})();
