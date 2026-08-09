// Single fetch wrapper for every call. It exists so that UI-7's error requirements are met in
// one place: every failure carries a human-readable message and a correlation ID that also went
// to the server, so a user can quote the ID and it can be found in the structured logs.

/** Absolute base URL of the FastAPI backend. Set VITE_API_BASE at build time for a deployed
 *  frontend (e.g. https://api.example.com); empty means same-origin, which is what the Vite dev
 *  proxy provides. No trailing slash. */
export const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

export class ApiError extends Error {
  readonly status: number;
  readonly correlationId: string;

  constructor(message: string, status: number, correlationId: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.correlationId = correlationId;
  }
}

const TOKEN_KEY = "cst.token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

function newCorrelationId(): string {
  return (
    crypto.randomUUID?.() ?? `cid-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
  );
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const correlationId = newCorrelationId();
  const token = getToken();
  const headers = new Headers(init.headers);
  headers.set("X-Correlation-Id", correlationId);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");

  let response: Response;
  try {
    response = await fetch(apiUrl(path), { ...init, headers });
  } catch {
    throw new ApiError("Cannot reach the server. Check that the API is running.", 0, correlationId);
  }

  if (response.status === 401) {
    clearToken();
    throw new ApiError("Your session is not valid. Sign in again.", 401, correlationId);
  }

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}.`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // non-JSON error body; keep the generic message
    }
    throw new ApiError(detail, response.status, correlationId);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T,>(path: string) => request<T>(path),
  post: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T,>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  put: <T,>(path: string, body: unknown) => request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  upload: <T,>(path: string, form: FormData) => request<T>(path, { method: "POST", body: form }),
};

/** Media is fetched with the same bearer token and handed to the player as an object URL,
 *  because an <audio src> cannot carry an Authorization header. */
export async function fetchMediaObjectUrl(path: string): Promise<string> {
  const token = getToken();
  const response = await fetch(apiUrl(path), {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  if (!response.ok) throw new ApiError("Could not load the attachment.", response.status, "n/a");
  return URL.createObjectURL(await response.blob());
}
