"use strict";
const tenant = location.pathname.split("/").filter(Boolean)[1];
const base = `/stores/${encodeURIComponent(tenant)}/api`;
const el = id => document.getElementById(id);
const storageKey = `commerce-shopper:${tenant}`;
let session = sessionStorage.getItem(storageKey) || "";
async function api(path, method = "GET", body) {
  const response = await fetch(base + path, {method, headers: {"Content-Type": "application/json", "X-Session-Id": session}, body: body ? JSON.stringify(body) : undefined});
  if (!response.ok) throw new Error(response.status === 401 ? "Your session is unavailable. Reload to start again." : "The store is temporarily unavailable. Do not pay again; refresh your orders.");
  return response;
}
async function refresh() {
  if (!session) return;
  el("cart").textContent = JSON.stringify(await (await api("/cart")).json(), null, 2);
  el("orders").textContent = JSON.stringify(await (await api("/orders")).json(), null, 2);
}
function showError(error) { el("status").textContent = error.message; }
el("chat").onsubmit = async event => {
  event.preventDefault(); el("send").disabled = true; el("status").textContent = "Thinking…";
  const message = event.target.elements.message.value;
  const question = document.createElement("p"); question.textContent = `You: ${message}`;
  const answer = document.createElement("p"); el("conversation").append(question, answer);
  try {
    const response = await api("/chat", "POST", {message});
    const reader = response.body.getReader(); const decoder = new TextDecoder(); let pending = "";
    while (true) {
      const {done, value} = await reader.read(); if (done) break;
      pending += decoder.decode(value, {stream: true});
      let boundary;
      while ((boundary = pending.indexOf("\n\n")) >= 0) {
        const frame = pending.slice(0, boundary); pending = pending.slice(boundary + 2);
        const type = frame.split("\n").find(line => line.startsWith("event: "))?.slice(7);
        const raw = frame.split("\n").find(line => line.startsWith("data: "))?.slice(6);
        if (!raw) continue; const data = JSON.parse(raw);
        if (type === "text_delta") answer.textContent += data.text || "";
        if (type === "error") throw new Error(data.message || "Request failed");
        if (type === "ui") {
          const detail = document.createElement("pre"); detail.textContent = JSON.stringify(data.payload, null, 2); el("conversation").append(detail);
          for (const handoff of data.payload?.handoffs || []) {
            const url = new URL(handoff.url); if (url.protocol !== "https:") continue;
            const link = document.createElement("a"); link.href = url.href; link.textContent = handoff.label || "Continue to secure checkout";
            link.target = "_blank"; link.rel = "noopener noreferrer"; el("conversation").append(link);
          }
        }
      }
    }
    event.target.reset(); await refresh(); el("status").textContent = "";
  } catch (error) { showError(error); }
  finally { el("send").disabled = false; }
};
el("refresh").onclick = () => refresh().catch(showError);
window.addEventListener("focus", () => refresh().catch(showError));
(async () => {
  const health = await (await api("/health")).json(); el("store-name").textContent = `${health.store} assistant`;
  if (session) {
    const response = await fetch(base + "/cart", {headers: {"X-Session-Id": session}});
    if (response.status === 401) { session = ""; sessionStorage.removeItem(storageKey); }
  }
  if (!session) { session = (await (await api("/session", "POST", {})).json()).session_id; sessionStorage.setItem(storageKey, session); }
  await refresh();
})().catch(showError);
