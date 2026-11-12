// Pure rendering helpers. Everything returns an HTML string; app.js delegates clicks
// through data-action attributes. No inline handlers so the MV3 CSP stays intact.

/* ---------------- primitives ---------------- */
export function esc(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

const PATHS = {
  spark: '<path d="M12 2.5c.4 4.6 2.4 7.4 7.5 8-5.1.6-7.1 3.4-7.5 8-.4-4.6-2.4-7.4-7.5-8 5.1-.6 7.1-3.4 7.5-8z" fill="currentColor" stroke="none"/><path d="M19 15c.2 2 .9 3 3 3.2-2.1.3-2.8 1.3-3 3.3-.2-2-.9-3-3-3.3 2.1-.2 2.8-1.2 3-3.2z" fill="currentColor" stroke="none" opacity=".7"/>',
  box: '<path d="M3.5 7.5 12 3.5l8.5 4v9L12 20.5l-8.5-4z"/><path d="M3.5 7.5 12 11.5l8.5-4M12 11.5v9"/>',
  bag: '<path d="M5 8.5h14l-1 11.5H6z"/><path d="M9 8.5V7a3 3 0 0 1 6 0v1.5"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3M8.5 21h7"/>',
  'arrow-up': '<path d="M12 19V5M6 11l6-6 6 6"/>',
  'arrow-right': '<path d="M5 12h14M13 6l6 6-6 6"/>',
  stop: '<rect x="6.5" y="6.5" width="11" height="11" rx="2" fill="currentColor" stroke="none"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21a2 2 0 0 1-4 0v-.09A1.7 1.7 0 0 0 8.5 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.6-1H3a2 2 0 0 1 0-4h.09A1.7 1.7 0 0 0 4.6 8.5a1.7 1.7 0 0 0-.34-1.88l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.6V3a2 2 0 0 1 4 0v.09A1.7 1.7 0 0 0 15 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 9v.5a1.7 1.7 0 0 0 1.6 1H21a2 2 0 0 1 0 4h-.09a1.7 1.7 0 0 0-1.51 1z"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5 21 21"/>',
  home: '<path d="M3.5 10.5 12 3.5l8.5 7V20a1 1 0 0 1-1 1h-5v-6h-5v6h-5a1 1 0 0 1-1-1z"/>',
  tag: '<path d="M3.5 11.5V4a.5.5 0 0 1 .5-.5h7.5l9 9-8 8z"/><circle cx="7.5" cy="7.5" r="1.3"/>',
  edit: '<path d="M4 20h4l10.5-10.5-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  'chevron-left': '<path d="M15 5l-7 7 7 7"/>',
  'chevron-right': '<path d="M9 5l7 7-7 7"/>',
  external: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
  star: '<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1-5.4-2.9-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z" fill="currentColor" stroke="none"/>',
  check: '<path d="M5 12.5 10 17l9-10"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  receipt: '<path d="M6 3h12v18l-2-1.3-2 1.3-2-1.3-2 1.3-2-1.3L6 21z"/><path d="M9 8h6M9 12h6"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2 6M20 5v6h-6"/>',
};

export function icon(name, size = 16) {
  return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${PATHS[name] || PATHS.info}</svg>`;
}

export function money(value, currency = 'USD') {
  const n = Number(value || 0);
  try { return new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(n); }
  catch { return `$${n.toFixed(2)}`; }
}
export function shortMoney(value, currency = 'USD') {
  const m = money(value, currency);
  return m.endsWith('.00') ? m.slice(0, -3) : m;
}
export function dateLabel(iso) {
  if (!iso) return '';
  const d = new Date(String(iso).length === 10 ? `${iso}T12:00:00Z` : iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' });
}
export function longDate(now) {
  return now.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });
}
export function greeting(now) {
  const h = now.getHours();
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
}
export function plural(n, word) { return `${n} ${word}${n === 1 ? '' : 's'}`; }
export function slugStatus(status) { return String(status || '').replace(/\s+/g, '_'); }
export const STATUS_LABELS = {
  processing: 'Processing', shipped: 'Shipped', out_for_delivery: 'Out for delivery',
  delivered: 'Delivered', delayed: 'Delayed', cancelled: 'Cancelled',
  return_initiated: 'Return requested', refunded: 'Refunded',
};
export function statusLabel(s) { return STATUS_LABELS[s] || String(s || '').replace(/_/g, ' '); }
export function statusChip(status) {
  return `<span class="status-chip ${esc(slugStatus(status))}">${esc(statusLabel(status))}</span>`;
}
/** Image-less products get a tinted tile and a glyph, mirroring lib/format.ts in the portal. */
function hash(text) {
  let v = 0;
  for (let i = 0; i < text.length; i++) v = (v * 31 + text.charCodeAt(i)) >>> 0;
  return v;
}
const KEYWORD_GLYPHS = [
  ['coffee', '☕'], ['skillet', '🍳'], ['knife', '🔪'], ['blender', '🥤'],
  ['bed frame', '🛏️'], ['mattress', '🛏️'], ['duvet', '🛌'], ['pillow', '🛌'],
  ['lamp', '💡'], ['rug', '🟫'], ['curtain', '🪟'], ['plush', '🧸'],
  ['palette', '💄'], ['mascara', '💄'], ['serum', '🧴'], ['tent', '⛺'],
  ['sleeping bag', '🛌'], ['stove', '🔥'], ['lantern', '🏮'],
  ['headphone', '🎧'], ['monitor', '🖥️'], ['keyboard', '⌨️'], ['mouse', '🖱️'],
  ['chair', '🪑'], ['desk', '🖥️'], ['stand', '💻'], ['webcam', '📷'],
  ['dog', '🐕'], ['cat', '🐈'], ['leash', '🦮'], ['pet', '🐾'],
  ['brick', '🧱'], ['book', '📚'], ['puzzle', '🧩'], ['game', '🎲'],
];
const CATEGORY_GLYPHS = {
  'home-kitchen': ['🍳', '🫖', '🥘', '🔪'],
  'office-electronics': ['🖥️', '⌨️', '🎧', '🖱️'],
  'outdoor-camping': ['⛺', '🔦', '🥾', '🏕️'],
  fitness: ['🏋️', '🧘', '💪', '🤸'],
  'toys-games': ['🦖', '🧩', '🎲', '🧸'],
  'pet-supplies': ['🐾', '🐕', '🐈', '🦴'],
  'beauty-personal-care': ['🌿', '🧴', '💄', '🪞'],
  travel: ['🧳', '🎒', '🌍', '✈️'],
  'kids-room': ['🦕', '🦖', '🌋', '🧸'],
  'furniture-bedroom': ['🛏️', '🛌', '🪑', '🕯️'],
  grocery: ['🥕', '🍎', '🧀', '🥫'],
};
const TILE_COLORS = [
  ['#fef3c7', '#fde68a'], ['#d1fae5', '#a7f3d0'], ['#e0f2fe', '#bae6fd'],
  ['#ffe4e6', '#fecdd3'], ['#ede9fe', '#ddd6fe'], ['#ecfccb', '#d9f99d'],
  ['#ffedd5', '#fed7aa'], ['#cffafe', '#a5f3fc'],
];
export function glyphFor(product) {
  const title = String(product?.title || '').toLowerCase();
  for (const [keyword, glyph] of KEYWORD_GLYPHS) if (title.includes(keyword)) return glyph;
  const pool = CATEGORY_GLYPHS[product?.category] || ['🛍️'];
  return pool[hash(product?.product_id || title) % pool.length];
}
export function imageBox(product, api, cls = 'tile-image') {
  const url = api.assetUrl(product?.image_url);
  const pair = TILE_COLORS[hash(product?.product_id || product?.title || 'x') % TILE_COLORS.length];
  const size = cls === 'thumb' ? 'font-size:17px' : cls === 'detail-image' ? 'font-size:64px' : 'font-size:40px';
  return `<div class="${cls}"><div class="product-placeholder" style="background:linear-gradient(135deg,${pair[0]},${pair[1]})"><span style="background:transparent;width:auto;height:auto;${size}">${glyphFor(product)}</span></div>${url ? `<img src="${esc(url)}" alt="" loading="lazy">` : ''}</div>`;
}

/** Small, safe markdown subset: headings, bold/italic, links, lists, code, paragraphs. */
export function markdown(raw) {
  const text = String(raw || '');
  const codeBlocks = [];
  let src = text.replace(/```[\w-]*\n?([\s\S]*?)```/g, (_m, code) => {
    codeBlocks.push(`<pre><code>${esc(code.trim())}</code></pre>`);
    return `\u0000CODE${codeBlocks.length - 1}\u0000`;
  });
  const inline = (line) => esc(line)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" data-action="open-url" data-url="$2">$1</a>');
  const lines = src.split('\n');
  const out = [];
  let list = null;
  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) { closeList(); continue; }
    const block = trimmed.match(/^\u0000CODE(\d+)\u0000$/);
    if (block) { closeList(); out.push(codeBlocks[Number(block[1])]); continue; }
    const heading = trimmed.match(/^(#{1,4})\s+(.*)$/);
    if (heading) { closeList(); out.push(`<h3>${inline(heading[2])}</h3>`); continue; }
    const bullet = trimmed.match(/^[-*•]\s+(.*)$/);
    if (bullet) { if (list !== 'ul') { closeList(); out.push('<ul>'); list = 'ul'; } out.push(`<li>${inline(bullet[1])}</li>`); continue; }
    const numbered = trimmed.match(/^\d+[.)]\s+(.*)$/);
    if (numbered) { if (list !== 'ol') { closeList(); out.push('<ol>'); list = 'ol'; } out.push(`<li>${inline(numbered[1])}</li>`); continue; }
    closeList();
    out.push(`<p>${inline(trimmed)}</p>`);
  }
  closeList();
  return out.join('');
}

/* ---------------- home ---------------- */
const STARTERS = [
  { icon: 'search', prompt: 'A tent for a first family camping trip, under $250' },
  { icon: 'home', prompt: 'Set up a home office in a small spare room for about $800' },
  { icon: 'tag', prompt: 'Drip or espresso for busy weekday mornings?' },
  { icon: 'edit', prompt: 'Remember: small apartment, no outdoor storage, and a golden retriever' },
];
export const OPEN_STATUSES = new Set(['processing', 'shipped', 'out_for_delivery', 'delayed', 'return_initiated']);
export function upcoming(orders) { return (orders || []).filter((o) => OPEN_STATUSES.has(o.status)); }
function estimateOf(order) { return order?.estimated_delivery || null; }

export function renderHome(state, api) {
  const orders = state.orders;
  const open = upcoming(orders || []);
  const late = open.filter((o) => o.status === 'delayed');
  const nextOrder = open.find((o) => o.status !== 'delayed') || open[0];
  const next = estimateOf(nextOrder);
  const brief = orders === null
    ? 'Ask about a product, a project, an order, or a return.'
    : !open.length
      ? 'Nothing on the way right now. Ask about a product, a project, or a return.'
      : `${plural(open.length, 'order')} on the way${next ? `; the next arrives ${esc(dateLabel(next))}` : ''}. ${late.length ? `<b>${late.length === 1 ? 'One is' : `${late.length} are`} running late.</b>` : ''}`;

  const catalog = state.catalog || [];
  const byId = new Map(catalog.map((p) => [p.product_id, p]));
  const featured = catalog
    .filter((p) => (p.labels || []).some((l) => l === 'bestseller' || l === 'new') && p.in_stock !== false)
    .sort((a, b) => Number(Boolean(b.image_url)) - Number(Boolean(a.image_url)))
    .slice(0, 4);
  const arriving = (open.length ? open : (orders || [])).slice(0, 3);

  return `<div class="home-inner">
    <div class="greeting">
      <div class="eyebrow">${esc(longDate(new Date()))}</div>
      <h1>${esc(greeting(new Date()))}, ${esc(state.shopper.name)}</h1>
      <div class="brief">${state.ordersFailed ? 'Orders could not be loaded. ' : ''}${brief}</div>
    </div>

    <div class="starters">
      ${STARTERS.map((s) => `<button type="button" class="starter" data-action="ask" data-prompt="${esc(s.prompt)}">
        <span class="starter-icon">${icon(s.icon, 15)}</span>
        <span class="starter-label">${esc(s.prompt)}</span>
        <span class="starter-arrow">${icon('arrow-right', 14)}</span>
      </button>`).join('')}
    </div>

    <div class="panel">
      <div class="panel-head">
        <h2>Arriving</h2><span class="muted">${plural((orders || []).length, 'order')}</span>
        <span class="spacer"></span>
        <button type="button" class="text-link" data-action="view" data-view="orders">All orders →</button>
      </div>
      ${arriving.length ? arriving.map((order) => {
        const first = order.items?.[0] || {};
        const product = byId.get(first.product_id) || { title: first.title, brand: '', image_url: null };
        const more = (order.items?.length || 1) - 1;
        const delayed = order.status === 'delayed';
        const prompt = delayed
          ? `Why is order ${order.order_id} delayed, and what can I do?`
          : `Where is order ${order.order_id} right now?`;
        return `<div class="arriving-row">
          ${imageBox(product, api, 'thumb')}
          <div class="arriving-meta">
            <div class="arriving-title">${esc(first.title || product.title || 'Order')}${more > 0 ? ` +${more} more` : ''}</div>
            <div class="arriving-sub">${statusChip(order.status)}
              <span>${delayed ? 'Expected' : 'Arrives'} ${esc(dateLabel(order.estimated_delivery))}</span>
            </div>
          </div>
          <button type="button" class="ask-btn" data-action="ask" data-prompt="${esc(prompt)}">${delayed ? 'Ask why' : 'Ask'}</button>
        </div>`;
      }).join('') : `<div class="cart-empty">No orders to show yet.</div>`}
    </div>

    ${featured.length ? `<div class="home-section">
      <div class="home-section-head"><h2>Popular right now</h2><p>Bestsellers and new arrivals; open one to ask about it</p></div>
      <div class="product-grid">${featured.map((p) => productTile(p, api)).join('')}</div>
    </div>` : ''}
  </div>`;
}

function productTile(p, api) {
  const attrs = Object.entries(p.attributes || {}).slice(0, 2).map(([, v]) => v).join(' · ');
  return `<button type="button" class="product-tile" data-action="ask" data-prompt="Tell me about the ${esc(p.title)}.">
    ${imageBox(p, api)}
    <div class="tile-body">
      <div class="tile-brand">${esc(p.brand || '')}</div>
      <div class="tile-title">${esc(p.title)}</div>
      ${attrs ? `<div class="tile-spec">${esc(attrs)}</div>` : ''}
      <div class="tile-foot">
        <span class="tile-price">${esc(money(p.price, p.currency))}</span>
        ${p.rating ? `<span class="tile-rating"><span class="star">${icon('star', 11)}</span>${esc(p.rating)} (${esc(p.review_count || 0)})</span>` : ''}
      </div>
      ${p.attributes?.delivery ? `<div class="tile-delivery">${esc(p.attributes.delivery)}</div>` : ''}
    </div>
  </button>`;
}

/* ---------------- orders view ---------------- */
export function renderOrders(state, api, filter = 'all') {
  const orders = state.orders || [];
  const open = upcoming(orders);
  const late = open.filter((o) => o.status === 'delayed');
  const past = orders.filter((o) => !OPEN_STATUSES.has(o.status));
  const groups = {
    all: orders,
    transit: open,
    delayed: late,
    past,
  };
  const labels = { all: 'All', transit: 'On the way', delayed: 'Delayed', past: 'Past' };
  const counts = { all: orders.length, transit: open.length, delayed: late.length, past: past.length };
  const shown = groups[filter] || orders;
  const byId = new Map((state.catalog || []).map((p) => [p.product_id, p]));
  const subtitle = late.length
    ? `${plural(late.length, 'order')} running late. Ask why, or about a return on anything delivered.`
    : `${plural(open.length, 'order')} on the way. Ask about any of them, or about a return on anything delivered.`;

  return `<div class="orders-inner">
    <div class="page-head"><h1>Orders</h1><p>${esc(state.ordersFailed ? 'Orders could not be loaded. The assistant can still look them up.' : subtitle)}</p></div>
    ${state.ordersFailed ? `<div class="notice">Couldn't load your orders. The assistant can still look them up.</div>` : ''}
    <div class="segmented">${Object.keys(labels).map((k) =>
      `<button type="button" class="${k === filter ? 'active' : ''}" data-action="order-filter" data-filter="${k}">${esc(labels[k])} ${counts[k]}</button>`
    ).join('')}</div>
    <div class="panel">
      ${shown.length ? shown.map((o) => {
        const first = o.items?.[0] || {};
        const product = byId.get(first.product_id) || { title: first.title, image_url: null };
        const more = (o.items?.length || 1) - 1;
        const prompt = o.status === 'delayed'
          ? `Why is order ${o.order_id} delayed, and what can I do?`
          : !OPEN_STATUSES.has(o.status)
            ? `Can I still return something from order ${o.order_id}?`
            : `Where is order ${o.order_id} right now?`;
        return `<div class="order-row">
          <div class="order-thumbs">${imageBox(product, api, 'thumb')}</div>
          <div class="order-meta">
            <div class="order-title">${esc(first.title || product.title || 'Order')}${more > 0 ? ` +${more} more` : ''}</div>
            <div class="order-sub">${esc(o.order_id)} ${statusChip(o.status)}</div>
          </div>
          <div class="order-when">${o.estimated_delivery ? esc(dateLabel(o.estimated_delivery)) : ''}</div>
          <div class="order-total">${esc(money(o.total, o.currency))}</div>
          <button type="button" class="ask-btn" data-action="ask" data-prompt="${esc(prompt)}">Ask</button>
        </div>`;
      }).join('') : `<div class="cart-empty">No orders in this view.</div>`}
    </div>
  </div>`;
}

/* ---------------- cart ---------------- */
export const FREE_SHIPPING_THRESHOLD = 49;
export function renderCartBody(state, api) {
  const cart = state.cart || { items: [], item_count: 0, subtotal: 0, currency: 'USD' };
  const byId = new Map((state.catalog || []).map((p) => [p.product_id, p]));
  return `<div class="cart-head"><h2>Cart</h2><span class="count-badge">${cart.item_count || 0} items</span></div>
    ${cart.items?.length ? cart.items.map((item) => {
      const product = byId.get(item.product_id) || { title: item.title, image_url: item.image_url, brand: '' };
      const options = Object.values(item.option_values || {}).filter(Boolean).join(' · ');
      return `<div class="cart-line">
        ${imageBox(product, api, 'thumb')}
        <div class="cart-line-main">
          <div class="cart-brand">${esc(product.brand || '')}</div>
          <div class="cart-title">${esc(item.title || product.title)}</div>
          ${options ? `<div class="cart-options">${esc(options)}</div>` : ''}
          <div class="delivery-promise">Get it in 3–5 business days</div>
          <div class="cart-line-foot">
            <span class="cart-price">${esc(money(item.line_total ?? (item.price * item.quantity), cart.currency))}</span>
            <div class="stepper">
              <button type="button" data-action="qty" data-id="${esc(item.product_id)}" data-delta="-1" aria-label="Decrease quantity">−</button>
              <span>${item.quantity}</span>
              <button type="button" data-action="qty" data-id="${esc(item.product_id)}" data-delta="1" aria-label="Increase quantity">+</button>
            </div>
          </div>
          <button type="button" class="remove-link" data-action="remove" data-id="${esc(item.product_id)}" data-title="${esc(item.title)}">Remove</button>
        </div>
      </div>`;
    }).join('') : `<div class="cart-empty">Nothing in the cart yet.<br>Ask ACME Assistant for anything in the store.</div>`}`;
}
export function renderCartFooter(state) {
  const cart = state.cart || { subtotal: 0, currency: 'USD', item_count: 0 };
  const remaining = Math.max(0, FREE_SHIPPING_THRESHOLD - Number(cart.subtotal || 0));
  const pct = Math.min(100, (Number(cart.subtotal || 0) / FREE_SHIPPING_THRESHOLD) * 100);
  return `<div class="shipping-meter">${remaining > 0
    ? `${esc(money(remaining, cart.currency))} away from free shipping`
    : 'Free shipping unlocked'}</div>
    <div class="meter-track"><div class="meter-fill" style="width:${pct}%"></div></div>
    <div class="cart-total"><span>Subtotal</span><span>${esc(money(cart.subtotal, cart.currency))}</span></div>
    <button type="button" class="btn-primary" data-action="checkout">${state.checkoutStaged ? 'View summary' : 'Check out'}</button>
    <button type="button" class="cart-ask" data-action="ask" data-prompt="Look over my cart: anything missing or worth swapping?">Ask about this cart</button>`;
}

/* ---------------- generative cards ---------------- */
function cardHead(title, sub = '') {
  return `<div class="card-head"><h3>${esc(title)}</h3>${sub ? `<span class="card-sub">${esc(sub)}</span>` : ''}</div>`;
}
function addButton(p) {
  return `<button type="button" class="add-btn" data-action="add" data-id="${esc(p.product_id)}" ${p.in_stock === false ? 'disabled title="Out of stock"' : ''}>${p.in_stock === false ? 'Out of stock' : 'Add'}</button>`;
}
function askProductButton(p) {
  return `<button type="button" class="plan-product" data-action="ask" data-prompt="Tell me about the ${esc(p.title)}.">${esc(p.title)}</button>`;
}
function miniProduct(p, api) {
  return `<button type="button" class="prod-card" data-action="product" data-id="${esc(p.product_id)}">
    ${imageBox(p, api)}
    <div class="tile-body">
      <div class="tile-brand">${esc(p.brand || '')}</div>
      <div class="tile-title">${esc(p.title)}</div>
      <div class="tile-foot"><span class="tile-price">${esc(money(p.price, p.currency))}</span>${p.rating ? `<span class="tile-rating"><span class="star">${icon('star', 11)}</span>${esc(p.rating)}</span>` : ''}</div>
    </div>
  </button>`;
}

export function renderCard(component, payload, api) {
  const p = payload || {};
  switch (component) {
    case 'products': {
      const items = (p.items || []).map((i) => ({ product: i.product || i, reason: i.reason })).filter((i) => i.product);
      const layout = p.layout === 'grid' || p.layout === 'list' ? p.layout : 'carousel';
      const tiles = items.map(({ product, reason }) => `<div class="prod-item">
        ${miniProduct(product, api)}
        ${reason ? `<div class="prod-reason">${esc(reason)}</div>` : ''}
        <div style="padding:0 0 10px 10px">${addButton(product)}</div>
      </div>`).join('');
      return `<div class="card" data-component="products">
        ${cardHead(p.title || 'Picks for you', `${items.length} items`)}
        <div class="${layout === 'grid' ? 'prod-grid' : layout === 'list' ? 'prod-list' : 'prod-scroll'}">${tiles}</div>
      </div>`;
    }
    case 'comparison': {
      const entries = p.entries || [];
      return `<div class="card" data-component="comparison">
        ${cardHead(p.title || 'Side by side', `${entries.length} compared`)}
        <div class="compare-grid">${entries.map((e) => {
          const product = e.product || {};
          const recommended = e.product_id && e.product_id === p.recommended_product_id;
          return `<div class="compare-col ${recommended ? 'recommended' : ''}">
            ${recommended ? '<div class="ribbon">Recommended</div>' : ''}
            <div class="compare-title">${esc(product.title || e.product_id)}</div>
            <div class="compare-price">${esc(money(product.price, product.currency))}</div>
            <ul class="compare-list pros">${(e.pros || []).map((x) => `<li>${esc(x)}</li>`).join('')}</ul>
            <ul class="compare-list cons">${(e.cons || []).map((x) => `<li>${esc(x)}</li>`).join('')}</ul>
            ${e.best_for ? `<div class="compare-best">Best for: ${esc(e.best_for)}</div>` : ''}
            <div style="margin-top:9px">${addButton(product)}</div>
          </div>`;
        }).join('')}</div>
        ${p.dimensions?.length ? `<div class="compare-foot">Compared on: ${esc(p.dimensions.join(', '))}</div>` : ''}
        ${p.price_delta ? `<div class="compare-foot">Price difference: ${esc(money(p.price_delta.amount))}</div>` : ''}
      </div>`;
    }
    case 'plan': {
      const steps = p.steps || [];
      let cheapest = 0;
      steps.forEach((s) => {
        const prices = (s.products || []).map((x) => Number(x.price || 0));
        if (prices.length) cheapest += Math.min(...prices);
      });
      return `<div class="card" data-component="plan">
        ${cardHead(p.title || 'A plan', `${steps.length} steps`)}
        ${p.intro ? `<div class="card-note" style="padding:0 14px">${esc(p.intro)}</div>` : ''}
        <div class="plan-steps">${steps.map((s, i) => `<div class="plan-step">
          <div class="step-num">${i + 1}</div>
          <div><div class="plan-label">${esc(s.label)}</div>
          ${s.detail ? `<div class="plan-detail">${esc(s.detail)}</div>` : ''}
          <div class="plan-products">${(s.products || []).map((x) => askProductButton(x)).join('')}</div></div>
        </div>`).join('')}</div>
        ${cheapest ? `<div class="budget-bar"><span>Starting budget</span><strong>${esc(money(cheapest))}</strong></div>` : ''}
      </div>`;
    }
    case 'guide': {
      return `<div class="card" data-component="guide">
        ${cardHead(p.title || 'A quick guide')}
        ${(p.sections || []).map((s) => `<div class="guide-section"><h4>${esc(s.heading)}</h4><p>${markdown(s.body)}</p></div>`).join('')}
        ${p.related_products?.length ? `<div class="guide-section"><h4>Related</h4><div class="plan-products">${p.related_products.map((x) => askProductButton(x)).join('')}</div></div>` : ''}
        ${p.sources?.length ? `<div class="guide-sources">Sources: ${esc(p.sources.join(' · '))}</div>` : ''}
      </div>`;
    }
    case 'order_status': {
      const o = p.order || {};
      const stages = [
        { key: 'processing', label: 'Ordered' },
        { key: 'shipped', label: 'Packed' },
        { key: 'out_for_delivery', label: 'Shipped' },
        { key: 'delivered', label: 'Delivered' },
      ];
      const order = ['processing', 'shipped', 'out_for_delivery', 'delivered'];
      const idx = Math.max(0, order.indexOf(o.status));
      const delayed = o.status === 'delayed';
      return `<div class="card" data-component="order_status">
        ${cardHead(`Order ${p.order_id || o.order_id || ''}`)}
        <div class="card-body">
          <div class="mini-row">${statusChip(o.status || 'processing')}<span class="card-sub">${esc(p.summary || '')}</span></div>
          <div class="rail">${stages.map((s, i) => `<div class="rail-step ${i <= idx ? 'done' : ''} ${delayed && i === 2 ? 'late' : ''}"><span class="rail-line"></span>${esc(s.label)}</div>`).join('')}</div>
          <div class="checkout-lines">${(o.items || []).map((it) => `<div class="checkout-line"><span>${esc(it.quantity)} × ${esc(it.title)}</span><span>${esc(money((it.price || 0) * (it.quantity || 1), o.currency))}</span></div>`).join('')}</div>
          <div class="totals"><div class="total-row grand"><span>Total</span><span>${esc(money(o.total, o.currency))}</span></div></div>
          ${p.next_step ? `<p class="card-note" style="margin-top:10px">${esc(p.next_step)}</p>` : ''}
          ${o.tracking_url && /^https?:\/\//.test(o.tracking_url) ? `<div class="handoffs"><button type="button" class="handoff" data-action="open-url" data-url="${esc(o.tracking_url)}">${icon('external', 13)} Track package</button></div>` : ''}
        </div>
      </div>`;
    }
    case 'checkout': {
      const cart = p.cart || { items: [], subtotal: 0, currency: 'USD' };
      const receipt = p.receipt;
      const handoffs = (p.handoffs || []).filter((h) => h && /^https?:\/\//.test(h.url || ''));
      const shipping = Number(cart.subtotal || 0) >= FREE_SHIPPING_THRESHOLD ? 0 : 5.99;
      return `<div class="card" data-component="checkout" data-checkout-card>
        <div class="card-head" style="align-items:center">
          <h3>${receipt ? 'PayPal order ready for approval' : 'Ready to check out'}</h3>
          <span class="badge-top ${receipt ? 'awaiting' : ''}">${receipt ? 'Awaiting approval' : 'Not charged'}</span>
        </div>
        <div class="card-body">
          ${p.note ? `<p class="card-note">${esc(p.note)}</p>` : ''}
          ${p.fulfillment_method ? `<div class="card-note">Fulfilment: ${esc(p.fulfillment_method)}</div>` : ''}
          <div class="checkout-lines">${(cart.items || []).map((it) => `<div class="checkout-line"><span>${esc(it.quantity)} × ${esc(it.title)}</span><span>${esc(money(it.line_total ?? (it.price * it.quantity), cart.currency))}</span></div>`).join('')}</div>
          <div class="totals">
            <div class="total-row"><span>Subtotal</span><span>${esc(money(cart.subtotal, cart.currency))}</span></div>
            <div class="total-row"><span>Shipping (3–5 business days)</span><span>${shipping ? esc(money(shipping, cart.currency)) : 'Free'}</span></div>
            <div class="total-row"><span>Tax</span><span>Calculated at checkout</span></div>
            <div class="total-row grand"><span>Estimated total</span><span>${esc(money(Number(cart.subtotal || 0) + shipping, cart.currency))}</span></div>
          </div>
          <p class="card-note" style="margin-top:9px">Most items can be returned within 30 days of delivery.</p>
          ${receipt ? `<div class="receipt" data-payment-receipt>
            <h4>Bounded auto-buy receipt</h4>
            <div class="receipt-grid">
              <span class="k">PayPal order id</span><span class="v">${esc(receipt.paypal_order_id || '—')}</span>
              <span class="k">Authorised cap</span><span class="v">${esc(receipt.spend_cap || '—')}</span>
              <span class="k">Amount</span><span class="v">${esc(receipt.currency || '')} ${esc(receipt.amount || '—')}</span>
              <span class="k">Status</span><span class="v">${esc(receipt.status || '—')}</span>
              <span class="k">Checkout id</span><span class="v">${esc(receipt.checkout_id || '—')}</span>
              <span class="k">Cart hash</span><span class="v">${esc(String(receipt.cart_hash || '—').slice(0, 16))}…</span>
            </div>
          </div>` : ''}
          <div class="handoffs">
            ${handoffs.map((h) => `<button type="button" class="handoff" data-action="open-url" data-url="${esc(h.url)}">${icon('external', 13)} ${esc(h.label || 'Continue to PayPal checkout')}</button>`).join('')}
            ${!handoffs.length ? `<button type="button" class="btn-primary" disabled>Continue to checkout</button>` : ''}
          </div>
        </div>
      </div>`;
    }
    case 'disclosure': {
      return `<div class="card" data-component="disclosure">
        ${cardHead(p.title || 'Disclosure', p.product_id || '')}
        <div class="card-body">
          <table class="spec-table">${(p.rows || []).map((r) => `<tr><td>${esc(r.label)}</td><td>${esc(r.value)}${r.note ? ` <span class="card-sub">(${esc(r.note)})</span>` : ''}</td></tr>`).join('')}</table>
          ${p.footnotes?.length ? `<p class="card-note">${esc(p.footnotes.join(' '))}</p>` : ''}
          ${p.sources?.length ? `<div class="guide-sources">Sources: ${esc(p.sources.join(' · '))}</div>` : ''}
        </div>
      </div>`;
    }
    default:
      return `<div class="card" data-component="${esc(component)}"><div class="card-body"><p class="card-note">This page has no view for “${esc(component)}” yet.</p></div></div>`;
  }
}

export function cardSkeleton(component) {
  return `<div class="card card-skeleton" data-skeleton="${esc(component)}">
    <div class="shimmer" style="width:45%"></div><div class="shimmer" style="width:80%"></div>
    <div class="shimmer" style="width:65%"></div><div class="shimmer" style="width:30%;height:34px;border-radius:8px"></div>
  </div>`;
}

/* ---------------- sheets ---------------- */
export function renderActivitySheet(state) {
  const turns = state.turns;
  const i = Math.max(0, Math.min(state.activityIndex ?? turns.length - 1, Math.max(0, turns.length - 1)));
  const t = turns[i];
  const nav = `<div class="reply-nav">
    <button type="button" data-action="reply-prev" ${i <= 0 ? 'disabled' : ''}>${icon('chevron-left', 14)}</button>
    <span>Reply ${turns.length ? i + 1 : 0} of ${turns.length}${t?.streaming ? ' · working…' : ''}</span>
    <button type="button" data-action="reply-next" ${i >= turns.length - 1 ? 'disabled' : ''}>${icon('chevron-right', 14)}</button>
  </div>`;
  if (!turns.length) return `${nav}<p class="card-note">No replies yet. Ask the assistant something to see its tool trace.</p>`;
  const steps = (t.steps || []).map((s) => {
    const glyph = s.status === 'ok' ? '✓' : s.status === 'blocked' ? '◦' : s.status === 'error' ? '✕' : '◌';
    const cls = s.status || 'running';
    return `<div class="step-row">
      <div class="step-title"><span class="step-glyph ${esc(cls)}">${glyph}</span>${esc(s.tool || 'tool')}
        <span class="card-sub">${esc(s.status === 'ok' ? 'ok' : s.status === 'blocked' ? `held · ${s.reason || 'gate'}` : s.status === 'error' ? 'error' : 'running…')}</span></div>
      <div class="step-meta">${esc(s.summary || '')}${s.elapsed != null ? ` · ${s.elapsed} ms` : ''}</div>
      <details><summary class="step-meta" style="cursor:pointer">Input</summary><div class="step-json">${esc(JSON.stringify(s.input ?? {}, null, 2))}</div></details>
      ${s.excerpt ? `<details><summary class="step-meta" style="cursor:pointer">Result (excerpt)</summary><div class="step-json">${esc(s.excerpt)}</div></details>` : ''}
    </div>`;
  }).join('') || `<p class="card-note">No tool calls in this reply.</p>`;
  const usage = t.usage || {};
  return `${nav}
    <div class="sheet-section">
      <h3>${(t.steps || []).length} steps${t.elapsed_ms ? ` · ${(t.elapsed_ms / 1000).toFixed(1)}s` : ''}</h3>
      ${steps}
      ${usage.input_tokens != null ? `<div class="usage">tokens in ${usage.input_tokens} · out ${usage.output_tokens || 0} · cache read ${usage.cache_read_input_tokens || 0}</div>` : ''}
    </div>
    <div class="sheet-section"><h3>What ACME Assistant knows</h3>${factRows(state.memory, state.newMemoryKeys, false)}</div>`;
}

function factCategory(c) {
  return c === 'preference' ? 'Preference' : c === 'constraint' ? 'Rule' : 'About you';
}
function factRows(facts, newKeys, editable) {
  if (!facts?.length) return `<p class="card-note">Nothing saved yet.</p>`;
  const fresh = newKeys || new Set();
  return facts.map((f) => `<div class="fact-row" data-key="${esc(f.key)}">
    <div class="fact-head">${esc(factCategory(f.category))}${fresh.has(f.key) ? ' · <span style="color:var(--accent-ink)">New this session</span>' : ''}${f.updated_at ? ` · Saved ${esc(dateLabel(f.updated_at))}` : ''}</div>
    <div class="fact-value">${esc(f.value)}</div>
    ${editable ? `<div class="fact-actions">
      <button type="button" data-action="fact-edit" data-key="${esc(f.key)}">Edit</button>
      <button type="button" data-action="fact-forget" data-key="${esc(f.key)}">Forget</button>
    </div><div class="fact-editor" hidden></div>` : ''}
  </div>`).join('');
}
export function renderAccountSheet(state) {
  return `<div class="sheet-section">
    <div class="mini-row" style="gap:10px;margin-bottom:12px">
      <span class="avatar" style="width:38px;height:38px;font-size:15px">${esc((state.shopper.name || '?')[0])}</span>
      <div><strong style="font-size:14px">${esc(state.shopper.name)}</strong><div class="card-sub">${esc(state.shopper.tier || '')}</div></div>
    </div>
    <h3>What ACME Assistant knows · ${(state.memory || []).length} saved</h3>
    <p class="card-note">Only preferences and standing rules are kept. Card, account, phone, and email details are refused.</p>
    ${factRows(state.memory, state.newMemoryKeys, true)}
  </div>`;
}
export function renderFactEditor(value) {
  return `<textarea class="fact-edit" maxlength="200">${esc(value)}</textarea>
    <div class="fact-actions" style="margin-top:7px">
      <button type="button" data-action="fact-save">Save</button>
      <button type="button" data-action="fact-cancel">Cancel</button>
    </div>`;
}

export function renderSettingsSheet(state) {
  const h = state.health || {};
  return `<div class="sheet-section">
    <h3>Shop connection</h3>
    <div class="field"><label for="api-base">API base URL</label>
      <input id="api-base" type="text" value="${esc(state.base)}" spellcheck="false" autocomplete="off">
    </div>
    <div class="mini-row" style="gap:8px;flex-wrap:wrap">
      <button type="button" class="btn-primary" data-action="save-base">Save & reconnect</button>
      <button type="button" class="ask-btn" data-action="reset-session">Reset session</button>
      <button type="button" class="ask-btn" data-action="clear-chat">Clear conversation</button>
    </div>
    <p class="card-note" style="margin-top:9px">Default: https://shop.mimi.money — the same origin the storefront uses for /api/. The extension has host permission for shop.mimi.money and the local demo on ports 8000 (localhost / 127.0.0.1); another origin needs adding to host_permissions in manifest.json.</p>
  </div>
  <div class="sheet-section"><h3>Host status</h3>
    <div class="kv"><span class="k">Store</span><span class="v">${esc(h.store || '—')}</span></div>
    <div class="kv"><span class="k">Products</span><span class="v">${esc(h.products ?? '—')}</span></div>
    <div class="kv"><span class="k">Model</span><span class="v">${esc(h.model || '—')}</span></div>
    <div class="kv"><span class="k">Payments</span><span class="v">${esc(h.payments || 'not configured')}</span></div>
    <div class="kv"><span class="k">Skills</span><span class="v">${esc((h.skills || []).length ? h.skills.join(', ') : '—')}</span></div>
    <div class="kv"><span class="k">Session</span><span class="v">${esc(state.sessionId ? `${String(state.sessionId).slice(0, 10)}…` : '—')}</span></div>
  </div>
  <div class="sheet-section"><h3>About</h3>
    <p class="card-note">ACME Shop — PayPal Commerce AI Agent OS. This extension is a full client for the shop API: search, comparison, cart, orders, memory, voice input and cap-bounded PayPal checkout. No payment credential is ever held here; approval happens on PayPal's own page.</p>
  </div>`;
}

/* ---------------- product detail modal ---------------- */
export function renderProductDetail(p, api) {
  const specRows = Object.entries(p.specs || {});
  const attrRows = Object.entries(p.attributes || {});
  const pi = p.price_intelligence;
  const aspects = p.review_aspects?.aspects || [];
  let spark = '';
  if (pi?.series?.length) {
    const min = Math.min(...pi.series), max = Math.max(...pi.series);
    const pts = pi.series.map((v, i) => {
      const x = (i / (pi.series.length - 1)) * 300;
      const y = 48 - ((v - min) / (max - min || 1)) * 42;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    spark = `<div class="sheet-section" style="margin-top:14px">
      <h3>Price history · ${esc(pi.days)} days</h3>
      <svg class="sparkline" viewBox="0 0 300 54" preserveAspectRatio="none"><polyline points="${pts}" fill="none" stroke="var(--accent-strong)" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>
      <div class="card-sub">${esc(pi.verdict || '')}</div>
    </div>`;
  }
  return `<div class="product-detail">
    ${imageBox(p, api, 'detail-image')}
    <div class="detail-main">
      <div class="tile-brand">${esc(p.brand || '')}</div>
      <div class="detail-title">${esc(p.title)}</div>
      <div class="mini-row" style="gap:9px">
        <span class="detail-price">${esc(money(p.price, p.currency))}</span>
        ${p.rating ? `<span class="tile-rating"><span class="star">${icon('star', 13)}</span>${esc(p.rating)} (${esc(p.review_count || 0)})</span>` : ''}
        ${p.in_stock === false ? `<span class="status-chip delayed">Out of stock</span>` : ''}
      </div>
      <div class="detail-desc">${esc(p.long_description || p.short_description || '')}</div>
      ${specRows.length || attrRows.length ? `<table class="spec-table">${[...specRows, ...attrRows].map(([k, v]) => `<tr><td>${esc(k.replace(/_/g, ' '))}</td><td>${esc(v)}</td></tr>`).join('')}</table>` : ''}
      ${p.variants?.length ? `<div class="plan-products">${p.variants.map((v) => `<button type="button" class="plan-product" data-action="ask" data-prompt="Add the ${esc(v.title || p.title)} with ${esc(Object.values(v.option_values || {}).join(', '))} to my cart.">${esc(Object.values(v.option_values || {}).join(' · ') || v.title || 'Option')}</button>`).join('')}</div>` : ''}
      <div class="detail-actions">
        ${addButton(p)}
        <button type="button" class="ask-btn" data-action="ask" data-prompt="Tell me about the ${esc(p.title)}.">Ask the assistant</button>
      </div>
    </div>
  </div>
  ${spark}
  ${aspects.length ? `<div class="sheet-section"><h3>What reviewers mention</h3>${aspects.map((a) => `<div class="aspect-row"><span class="name">${esc(a.name)}</span><div class="aspect-bar"><span style="width:${Math.max(0, Math.min(100, a.positive_pct))}%"></span></div><span>${esc(a.positive_pct)}%</span></div>`).join('')}</div>` : ''}
  ${p.review_highlights?.length ? `<div class="sheet-section"><h3>Review highlights</h3><ul style="font-size:12px;padding-left:18px">${p.review_highlights.map((r) => `<li>${esc(r)}</li>`).join('')}</ul></div>` : ''}`;
}
