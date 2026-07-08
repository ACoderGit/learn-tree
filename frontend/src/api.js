export async function fetchGraph() {
  const r = await fetch("/api/graph");
  if (!r.ok) throw new Error("Failed to load graph");
  return r.json();
}

export async function fetchStatus() {
  try {
    const r = await fetch("/api/status");
    return r.ok ? r.json() : { provider: "unknown" };
  } catch {
    return { provider: "offline" };
  }
}

export async function addSource(url) {
  const r = await fetch("/api/add", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || "Failed to add source");
  return data;
}

async function postJSON(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || "Request failed");
  return data; // returns the updated graph
}

export const clearGraph = () => postJSON("/api/clear", {});
export const loadDemo = () => postJSON("/api/demo/load", {});
export const createPlane = (name) => postJSON("/api/plane/create", { name });
export const selectPlane = (name) => postJSON("/api/plane/select", { name });
export const deletePlane = (name) => postJSON("/api/plane/delete", { name });
export const recommend = (options) => postJSON("/api/recommend", options);
export const addNode = (label, level, parentId) =>
  postJSON("/api/node/add", { label, level, parentId });
export const renameNode = (id, label) => postJSON("/api/node/rename", { id, label });
export const setNodeLevel = (id, level) => postJSON("/api/node/level", { id, level });
export const deleteNode = (id) => postJSON("/api/node/delete", { id });
export const reviewNode = (id) => postJSON("/api/node/review", { id });
export const setTime = (days) => postJSON("/api/time/set", { days });
