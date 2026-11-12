// Service worker: owns the single full-screen shop tab and the toolbar action.
// Nothing here holds credentials or payment state; the app page talks to the shop API.

const APP_URL = chrome.runtime.getURL('app.html');

async function openApp() {
  const tabs = await chrome.tabs.query({});
  const existing = tabs.find((tab) => tab.url && tab.url.startsWith(APP_URL));
  if (existing) {
    await chrome.tabs.update(existing.id, { active: true });
    if (existing.windowId != null) {
      try { await chrome.windows.update(existing.windowId, { focused: true }); } catch { /* window closed */ }
    }
    return existing.id;
  }
  const tab = await chrome.tabs.create({ url: APP_URL });
  return tab.id;
}

chrome.action.onClicked.addListener(() => { void openApp(); });

chrome.runtime.onInstalled.addListener((details) => {
  try {
    chrome.contextMenus.create({
      id: 'acme-open-shop',
      title: 'Open ACME Shop',
      contexts: ['action'],
    });
  } catch { /* contextMenus unavailable in some profiles */ }
  if (details.reason === 'install') void openApp();
});

chrome.contextMenus.onClicked.addListener((info) => {
  if (info.menuItemId === 'acme-open-shop') void openApp();
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message && message.type === 'open-shop') {
    openApp().then((id) => sendResponse({ ok: true, tabId: id })).catch((e) => sendResponse({ ok: false, error: String(e) }));
    return true;
  }
  return false;
});
