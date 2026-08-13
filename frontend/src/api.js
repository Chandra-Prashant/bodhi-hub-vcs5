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

async function request(path, { method = "GET", body, raw = false } = {}) {
  const response = await fetch(BASE + path, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
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
  login: (email, password) =>
    request("/auth/login", { method: "POST", body: { email, password } }),
  me: () => request("/auth/me"),
  runAssessment: (payload) =>
    request("/assessment/run", { method: "POST", body: payload }),
  traceabilityCsv: (payload) =>
    request("/assessment/traceability.csv", { method: "POST", body: payload, raw: true }),
  regulatoryStatus: () => request("/assessment/regulatory-status"),
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
