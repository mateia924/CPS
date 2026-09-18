const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, body: unknown) {
    super(typeof body === "string" ? body : JSON.stringify(body));
    this.status = status;
    this.body = body;
  }
}

function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("cps_access");
}

function getLocale(): string {
  if (typeof window === "undefined") return "ar";
  return window.localStorage.getItem("cps_locale") ?? "ar";
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  auth = true
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  // Backend messages (validation errors, etc.) are translated per the
  // active Django language, chosen from this header — tied to the
  // app's own ar/en toggle so error text always matches the UI
  // language, instead of guessing from the browser's own Accept-Language.
  headers.set("Accept-Language", getLocale());
  if (auth) {
    const token = getAccessToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  } catch {
    // Network failure (server unreachable, DNS, CORS preflight rejected,
    // connection dropped) — never surfaced as an ApiError since there's
    // no HTTP response at all.
    throw new ApiError(0, { detail: "network_error" });
  }

  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      // Non-JSON body — an nginx/proxy error page (502/504 HTML) is the
      // usual cause. Wrap it so callers only ever deal with ApiError,
      // never a raw SyntaxError that bypasses their error handling.
      data = { detail: text.slice(0, 500) };
    }
  }

  if (!res.ok) {
    throw new ApiError(res.status, data);
  }
  return data as T;
}

/** DRF's standard error shape: {field: [msg, ...]} plus optionally
 * non_field_errors / detail. Never assume it — the server can also
 * return a flat {detail: "..."} for auth/permission errors. */
export function fieldErrors(body: unknown): Record<string, string> {
  if (!body || typeof body !== "object") return {};
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(body as Record<string, unknown>)) {
    if (Array.isArray(value)) {
      out[key] = value.map(String).join(" ");
    } else if (typeof value === "string") {
      out[key] = value;
    }
  }
  return out;
}

/** A single message to show when there's no better field to attach the
 * error to (network failure, {detail: "..."}, or an unrecognized shape). */
export function generalError(body: unknown, fallback: string): string {
  if (!body || typeof body !== "object") return fallback;
  const obj = body as Record<string, unknown>;
  if (typeof obj.detail === "string" && obj.detail !== "network_error") return obj.detail;
  if (obj.detail === "network_error") return fallback;
  if (Array.isArray(obj.non_field_errors)) return obj.non_field_errors.map(String).join(" ");
  return fallback;
}

export const api = {
  get: <T>(path: string) => request<T>(path, { method: "GET" }),
  post: <T>(path: string, body?: unknown, auth = true) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }, auth),
};
