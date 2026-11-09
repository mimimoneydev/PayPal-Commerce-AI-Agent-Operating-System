"use strict";
let csrf = "";
let accountingPage = 1;
const el = id => document.getElementById(id);
const tenantPath = () => `/api/merchants/${encodeURIComponent(el("merchants").value)}`;
async function api(path, method = "GET", body) {
  const response = await fetch(path, {method, credentials: "same-origin", headers: {
    "Content-Type": "application/json", "X-CSRF-Token": csrf,
  }, body: body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Request failed. Check your fields and permissions.");
  return data;
}
function run(action) { return async event => {
  event?.preventDefault();
  try { el("status").textContent = "Working…"; await action(event); el("status").textContent = "Done."; }
  catch (error) { el("status").textContent = error.message; }
}; }
async function refreshMerchant() {
  const selected = el("merchants").value;
  el("merchant").hidden = !selected;
  if (!selected) return;
  const connection = await api(tenantPath() + "/connection");
  el("connection-status").textContent = connection.configured ? `${connection.platform}: ${connection.url}` : "No store connected.";
  el("ledger").href = tenantPath() + "/ledger.csv";
  el("audit").textContent = JSON.stringify(await api(tenantPath() + "/audit"), null, 2);
  const work = await api(tenantPath() + "/operations");
  const reviews = document.createElement("pre"); reviews.textContent = JSON.stringify(work.reviews, null, 2);
  el("operations").replaceChildren(reviews, ...work.operations.map(row => {
    const section = document.createElement("section");
    const detail = document.createElement("pre"); detail.textContent = JSON.stringify(row, null, 2); section.append(detail);
    const action = row.data.status === "staged" ? "approve" : row.data.status === "approved" ? "execute" : null;
    if (action) {
      const button = document.createElement("button"); button.textContent = `${action === "approve" ? "Approve" : "Execute"} ${row.data.kind} ${row.key}`;
      button.onclick = run(async () => {
        if (!window.confirm(`${action} the displayed ${row.data.kind} for ${row.data.order_id}?`)) return;
        await api(tenantPath() + `/operations/${row.key}/${action}`, "POST", action === "approve" ? {version: row.version} : undefined);
        await refreshMerchant();
      }); section.append(button);
    }
    return section;
  }));
}
async function dashboard() {
  csrf = (await api("/api/me")).csrf;
  el("auth").hidden = true; el("dashboard").hidden = false;
  const previous = el("merchants").value;
  const merchants = await api("/api/merchants");
  el("merchants").replaceChildren(...merchants.map(merchant => {
    const option = document.createElement("option"); option.value = merchant.id;
    option.textContent = merchant.name; return option;
  }));
  if (merchants.some(m => m.id === previous)) el("merchants").value = previous;
  await refreshMerchant();
}
el("login").onsubmit = run(async event => {
  const action = event.submitter.value;
  const body = Object.fromEntries(new FormData(event.target));
  await api(`/api/${action}`, "POST", body);
  if (action === "register") await api("/api/login", "POST", body);
  event.target.reset(); await dashboard();
});
el("create").onsubmit = run(async event => {
  await api("/api/merchants", "POST", Object.fromEntries(new FormData(event.target)));
  event.target.reset(); await dashboard();
});
el("connection").onsubmit = run(async event => {
  await api(tenantPath() + "/connection", "PUT", Object.fromEntries(new FormData(event.target)));
  event.target.reset(); await refreshMerchant();
});
el("member").onsubmit = run(async event => {
  await api(tenantPath() + "/members", "POST", Object.fromEntries(new FormData(event.target)));
  event.target.reset(); await refreshMerchant();
});
el("ops-credentials").onsubmit = run(async event => {
  const body = Object.fromEntries(new FormData(event.target)); body.paypal_sandbox = event.target.elements.paypal_sandbox.checked;
  await api(tenantPath() + "/operations/credentials", "PUT", body); event.target.reset(); await refreshMerchant();
});
el("review").onsubmit = run(async event => {
  const body = Object.fromEntries(new FormData(event.target)); const order = body.order_id; delete body.order_id;
  await api(tenantPath() + `/reviews/${encodeURIComponent(order)}`, "PUT", body); await refreshMerchant();
});
el("operation").onsubmit = run(async event => {
  const body = Object.fromEntries(new FormData(event.target)); body.payload = JSON.parse(body.payload);
  await api(tenantPath() + "/operations", "POST", body); await refreshMerchant();
});
el("test").onclick = run(async () => { await api(tenantPath() + "/connection/test", "POST"); await refreshMerchant(); });
el("refresh").onclick = run(refreshMerchant);
el("sync-accounting").onclick = run(async () => {
  const result = await api(tenantPath() + "/accounting/sync", "POST", {page: accountingPage});
  accountingPage = result.next_page || 1;
  el("accounting-status").textContent = result.next_page ? `${result.orders} paid orders read. Click again for page ${result.next_page}.` : "Scan complete. Future scans start at page 1 to discover refunds and updates.";
  await refreshMerchant();
});
for (const id of ["publish", "unpublish"]) el(id).onclick = run(async () => {
  const result = await api(tenantPath() + "/publication", "PUT", {enabled: id === "publish"});
  el("storefront-url").textContent = result.enabled ? `Shopper page: /shop/${el("merchants").value}; Storefront API: ${result.api}; Shopify webhooks: /webhooks/shopify/${el("merchants").value}` : "Unpublished";
  await refreshMerchant();
});
el("merchants").onchange = run(async () => { accountingPage = 1; el("accounting-status").textContent = ""; await refreshMerchant(); });
el("logout").onclick = run(async () => { await api("/api/logout", "POST"); csrf = ""; location.reload(); });
dashboard().catch(() => { el("auth").hidden = false; });
