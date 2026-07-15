const BASE = import.meta.env?.VITE_API || "http://localhost:8000";
const h = (t) => ({ "Content-Type": "application/json", "X-Tenant-Id": t });

export async function ask(t, question) {
  return (await fetch(`${BASE}/v1/ask`, { method: "POST", headers: h(t), body: JSON.stringify({ question }) })).json();
}
export async function createApproval(t, req) {
  return (await fetch(`${BASE}/v1/approvals`, { method: "POST", headers: h(t), body: JSON.stringify(req) })).json();
}
export function reportUrl() { return `${BASE}/v1/report`; }
