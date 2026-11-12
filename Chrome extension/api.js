// HTTP client for the ACME storefront API.
// Contract is the same one shop.mimi.money uses (see examples/demo_common/storefront.py
// and examples/web-shared/api.ts). An MV3 extension page with host_permissions is
// allowed to call these endpoints cross-origin; Chrome bypasses CORS for that origin.

export const DEFAULT_BASE = 'https://shop.mimi.money';
const SESSION_HEADER = 'X-Session-Id';
const STORAGE_KEYS = { base: 'acme.base', session: 'acme.session' };

export async function loadBase() {
  const saved = await chrome.storage.local.get(STORAGE_KEYS.base);
  return saved[STORAGE_KEYS.base] || DEFAULT_BASE;
}
export async function saveBase(base) {
  await chrome.storage.local.set({ [STORAGE_KEYS.base]: base });
}
async function loadSession() {
  const saved = await chrome.storage.local.get(STORAGE_KEYS.session);
  return saved[STORAGE_KEYS.session] || null;
}
async function saveSession(id) {
  await chrome.storage.local.set({ [STORAGE_KEYS.session]: id });
}
export async function clearSession() {
  await chrome.storage.local.remove(STORAGE_KEYS.session);
}

/** Parse the SSE frames the host writes: `event: <type>\ndata: <json>\n\n`. */
export async function* readEventStream(body) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let eventType = null;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let newline;
    while ((newline = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, newline).trimEnd();
      buffer = buffer.slice(newline + 1);
      if (line.startsWith('event: ')) {
        eventType = line.slice(7).trim();
      } else if (line.startsWith('data: ') && eventType) {
        try {
          yield { type: eventType, data: JSON.parse(line.slice(6)) };
        } catch {
          // A malformed frame is dropped, exactly like the shipped client.
        }
      } else if (line === '') {
        eventType = null;
      }
    }
  }
}

export class ShopApi {
  constructor(base = DEFAULT_BASE) {
    this.base = String(base).replace(/\/+$/, '');
    this.session = null;
    this.shopper = { name: 'there', tier: '' };
    this.onSession = null; // callback(sessionInfo)
  }

  setBase(base) {
    this.base = String(base).replace(/\/+$/, '');
    this.session = null;
  }

  assetUrl(path) {
    if (!path) return null;
    return path.startsWith('/') ? `${this.base}${path}` : path;
  }

  headers(json = false) {
    const h = {};
    if (this.session) h[SESSION_HEADER] = this.session;
    if (json) h['Content-Type'] = 'application/json';
    return h;
  }

  async request(path, { method = 'GET', body, signal, retry = true } = {}) {
    const init = {
      method,
      headers: this.headers(body !== undefined),
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
      ...(signal ? { signal } : {}),
    };
    const response = await fetch(`${this.base}/api${path}`, init);
    if ((response.status === 401 || response.status === 409) && retry) {
      // Unknown/expired session or a concurrent write: start a new one and retry once.
      await this.ensureSession(true);
      return this.request(path, { method, body, signal, retry: false });
    }
    let data = null;
    try { data = await response.json(); } catch { /* non-JSON error body */ }
    return { ok: response.ok, status: response.status, data };
  }

  async get(path, params) {
    const q = params && Object.keys(params).length ? `?${new URLSearchParams(params)}` : '';
    const r = await this.request(`${path}${q}`);
    return r.ok ? r.data : null;
  }

  async post(path, body) {
    const r = await this.request(path, { method: 'POST', body });
    return r.ok ? r.data : null;
  }

  /** Bind a session to the demo profile; reuses a stored one when the host still knows it. */
  async ensureSession(force = false) {
    if (!force) {
      const stored = await loadSession();
      if (stored) {
        this.session = stored;
        const probe = await this.request('/cart', { retry: false });
        if (probe.ok) {
          this.shopper = await this.recallShopper();
          if (this.onSession) this.onSession(this.shopper);
          return this.shopper;
        }
      }
    }
    const r = await this.request('/session', { method: 'POST', body: {}, retry: false });
    if (!r.ok || !r.data || !r.data.session_id) {
      throw new Error(`Session start failed (HTTP ${r.status})`);
    }
    this.session = r.data.session_id;
    this.shopper = { name: r.data.name || 'there', tier: r.data.tier || '' };
    await saveSession(this.session);
    await chrome.storage.local.set({ 'acme.shopper': this.shopper });
    if (this.onSession) this.onSession(this.shopper);
    return this.shopper;
  }

  /** /api/session is POST-only, so the profile from the last session is cached locally. */
  async recallShopper() {
    const saved = await chrome.storage.local.get('acme.shopper');
    return saved['acme.shopper'] || { name: 'there', tier: '' };
  }

  async getHealth() { return this.get('/health'); }
  async getProducts(limit = 100) { return this.get('/products', { limit: String(limit) }); }
  async getProduct(id) { return this.get(`/products/${encodeURIComponent(id)}`); }
  async getCart() { return this.get('/cart'); }
  async getOrders() { return this.get('/orders'); }
  async getMemory() { return this.get('/memory'); }

  async addToCart(productId, quantity = 1) {
    const r = await this.request('/cart/add', { method: 'POST', body: { product_id: productId, quantity } });
    if (!r.ok) {
      const detail = r.data?.detail || `Could not add the item (HTTP ${r.status}).`;
      throw new Error(detail);
    }
    return r.data;
  }

  async patchMemory(key, value) {
    const r = await this.request('/memory', { method: 'PATCH', body: { key, value } });
    return r.ok ? r.data?.fact : null;
  }

  async deleteMemory(key) {
    const r = await this.request('/memory', { method: 'DELETE', body: { key } });
    return r.ok;
  }

  async reset({ clearMemory = false, purgeMemory = false } = {}) {
    const r = await this.request('/reset', {
      method: 'POST', body: { clear_memory: clearMemory, purge_memory: purgeMemory },
    });
    if (r.ok && r.data?.session_id) {
      this.session = r.data.session_id;
      await saveSession(this.session);
      return r.data.session_id;
    }
    // Some deployments answer without a new id; fall back to a fresh session.
    await this.ensureSession(true);
    return this.session;
  }

  /** POST /api/chat as a streaming SSE response. Retries once on a stale session. */
  async *chatStream(message, signal) {
    let response = await fetch(`${this.base}/api/chat`, {
      method: 'POST',
      headers: this.headers(true),
      body: JSON.stringify({ message }),
      ...(signal ? { signal } : {}),
    });
    if (response.status === 401 || response.status === 409) {
      await this.ensureSession(true);
      response = await fetch(`${this.base}/api/chat`, {
        method: 'POST',
        headers: this.headers(true),
        body: JSON.stringify({ message }),
        ...(signal ? { signal } : {}),
      });
    }
    if (!response.ok || !response.body) {
      throw new Error(`Chat request failed (HTTP ${response.status}).`);
    }
    yield* readEventStream(response.body);
  }
}
