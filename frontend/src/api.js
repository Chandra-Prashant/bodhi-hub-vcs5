/**
 * API client.
 *
 * The access token lives in memory only. Putting it in localStorage would make
 * it readable by any script on the page, and this system holds client project
 * data the customer has told us is sensitive. The trade-off is that a page
 * refresh signs you out, which is the correct trade for this audience.
 */

const BASE = "/api/v1";

let accessToken = null;
let refreshToken = null;
let onSessionLost = null;

export function setToken(token, refresh = null) {
  accessToken = token;
  refreshToken = refresh;
}

export function hasToken() {
  return Boolean(accessToken);
}

/** Called when the session cannot be renewed, so the app can sign out. */
export function setSessionLostHandler(handler) {
  onSessionLost = handler;
}

/**
 * Renew the access token.
 *
 * Access tokens are deliberately short-lived, which is right for a system
 * holding client project data — but until now nothing spent the refresh token,
 * so a session simply stopped working mid-task and the user lost whatever they
 * were part-way through. The refresh endpoint existed the whole time.
 *
 * A single in-flight refresh is shared: several requests failing at once must
 * not each start their own, or they invalidate one another.
 */
let refreshing = null;

async function renew() {
  if (!refreshToken) return false;
  if (!refreshing) {
    refreshing = fetch(BASE + "/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!data?.access_token) return false;
        accessToken = data.access_token;
        if (data.refresh_token) refreshToken = data.refresh_token;
        return true;
      })
      .catch(() => false)
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

async function send(path, { method, body, form }) {
  // A multipart body must NOT carry an explicit Content-Type — the browser has
  // to set it so it can append the boundary token.
  return fetch(BASE + path, {
    method,
    headers: {
      ...(form ? {} : { "Content-Type": "application/json" }),
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
    ...(form ? { body: form } : body ? { body: JSON.stringify(body) } : {}),
  });
}

async function request(path, { method = "GET", body, raw = false, form } = {}) {
  let response = await send(path, { method, body, form });

  // One retry after a renewal. Not a loop: if the second attempt is also
  // rejected the session is genuinely gone, and retrying further would hide
  // that behind a hang.
  if (response.status === 401 && refreshToken && !path.startsWith("/auth/")) {
    if (await renew()) {
      response = await send(path, { method, body, form });
    }
    if (response.status === 401) {
      accessToken = refreshToken = null;
      onSessionLost?.();
      throw new Error("Your session has expired. Sign in again.");
    }
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string") detail = payload.detail;
      else if (payload.detail?.message) detail = payload.detail.message;
    } catch {
      /* response had no JSON body; keep the status message */
    }
    throw new Error(detail);
  }

  return raw ? response.blob() : response.json();
}

export const api = {
  uploadDocument: (projectId, file) => {
    const form = new FormData();
    form.append("file", file);
    return request(`/documents/upload?project_id=${projectId}`,
                   { method: "POST", form });
  },
  login: (email, password) =>
    request("/auth/login", { method: "POST", body: { email, password } }),
  me: () => request("/auth/me"),
  runAssessment: (payload) =>
    request("/assessment/run", { method: "POST", body: payload }),
  traceabilityCsv: (payload) =>
    request("/assessment/traceability.csv", { method: "POST", body: payload, raw: true }),
  regulatoryStatus: () => request("/assessment/regulatory-status"),
  documents: (projectId) => request(`/documents?project_id=${projectId}`),
  reviewQueue: (projectId) =>
    request(`/documents/queue?project_id=${projectId}`),
  deleteDocument: (documentId) =>
    request(`/documents/${documentId}`, { method: "DELETE", raw: true }),
  assessDocument: (documentId) =>
    request(`/documents/${documentId}/assess`, { method: "POST" }),
  resolveReview: (itemId, state, correctedValue, note) =>
    request(`/documents/review/${itemId}`, {
      method: "POST",
      body: { state, corrected_value: correctedValue ?? null, note: note ?? null },
    }),
  esgSchema: () => request("/assessment/esg-schema"),
  esgReview: (payload) =>
    request("/assessment/esg-review", { method: "POST", body: payload }),
  documentStatus: (payload) =>
    request("/assessment/document-status", { method: "POST", body: payload }),
  // Projects
  listProjects: () => request("/projects"),
  createProject: (name, note = "") =>
    request("/projects", { method: "POST", body: { name, note } }),
  readProject: (id) => request(`/projects/${id}`),
  updateProject: (id, patch) =>
    request(`/projects/${id}`, { method: "PATCH", body: patch }),
  saveProjectState: (id, payload) =>
    request(`/projects/${id}/state`, { method: "PUT", body: payload }),
  assessProject: (id) =>
    request(`/projects/${id}/assess`, { method: "POST" }),
  deleteProject: (id) =>
    request(`/projects/${id}`, { method: "DELETE", raw: true }),

  readDraft: () => request("/assessment/draft"),
  writeDraft: (payload) =>
    request("/assessment/draft", { method: "PUT", body: payload }),
  clearDraft: () =>
    request("/assessment/draft", { method: "DELETE", raw: true }),
  projectDescription: (payload, stripGuidance = false) =>
    request(
      `/assessment/project-description?strip_guidance=${stripGuidance}`,
      { method: "POST", body: payload, raw: true }
    ),
};

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
