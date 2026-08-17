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

export function setToken(token) {
  accessToken = token;
}

export function hasToken() {
  return Boolean(accessToken);
}

async function request(path, { method = "GET", body, raw = false, form } = {}) {
  // A multipart body must NOT carry an explicit Content-Type — the browser has
  // to set it so it can append the boundary token.
  const response = await fetch(BASE + path, {
    method,
    headers: {
      ...(form ? {} : { "Content-Type": "application/json" }),
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
    ...(form ? { body: form } : body ? { body: JSON.stringify(body) } : {}),
  });

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
  uploadDocument: (file) => {
    const form = new FormData();
    form.append("file", file);
    return request("/documents/upload", { method: "POST", form });
  },
  login: (email, password) =>
    request("/auth/login", { method: "POST", body: { email, password } }),
  me: () => request("/auth/me"),
  runAssessment: (payload) =>
    request("/assessment/run", { method: "POST", body: payload }),
  traceabilityCsv: (payload) =>
    request("/assessment/traceability.csv", { method: "POST", body: payload, raw: true }),
  regulatoryStatus: () => request("/assessment/regulatory-status"),
  documents: () => request("/documents"),
  reviewQueue: () => request("/documents/queue"),
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
