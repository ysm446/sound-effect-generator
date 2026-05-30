// Thin client for the Python FastAPI backend.
// The backend host/port can be overridden by the Electron main process via a
// global injected on window; otherwise we default to localhost:8765.
const API_BASE =
  (typeof window !== "undefined" && window.__API_BASE__) ||
  "http://127.0.0.1:8765";

async function jsonOrThrow(res) {
  if (!res.ok) {
    let detail;
    try {
      detail = await res.json();
    } catch {
      detail = await res.text();
    }
    throw new Error(
      typeof detail === "string" ? detail : JSON.stringify(detail?.detail ?? detail)
    );
  }
  return res.json();
}

export const api = {
  base: API_BASE,

  health() {
    return fetch(`${API_BASE}/api/health`).then(jsonOrThrow);
  },

  listModels() {
    return fetch(`${API_BASE}/api/models`).then(jsonOrThrow);
  },

  setModel(model) {
    return fetch(`${API_BASE}/api/model`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model }),
    }).then(jsonOrThrow);
  },

  setEngine(name, action) {
    return fetch(`${API_BASE}/api/engine/${name}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    }).then(jsonOrThrow);
  },

  suggest(idea) {
    return fetch(`${API_BASE}/api/suggest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ idea }),
    }).then(jsonOrThrow);
  },

  createJob(params) {
    return fetch(`${API_BASE}/api/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    }).then(jsonOrThrow);
  },

  listJobs() {
    return fetch(`${API_BASE}/api/jobs`).then(jsonOrThrow);
  },

  deleteJob(id) {
    return fetch(`${API_BASE}/api/jobs/${id}`, { method: "DELETE" }).then(
      jsonOrThrow
    );
  },

  audioUrl(id) {
    return `${API_BASE}/api/audio/${id}`;
  },
};
