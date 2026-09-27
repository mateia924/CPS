export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, body: unknown) {
    super(typeof body === "string" ? body : JSON.stringify(body));
    this.status = status;
    this.body = body;
  }
}

function getAccessToken(tokenKey: string): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(tokenKey);
}

function getLocale(): string {
  if (typeof window === "undefined") return "ar";
  return window.localStorage.getItem("cps_locale") ?? "ar";
}

/** Sprint 6.5.10 (UAT note 7): the tenant realm ("cps_access") can be
 * silently refreshed via /auth/refresh/ — the platform realm
 * ("cps_platform_access") has no refresh endpoint at all (apps/
 * platform/urls.py), so a 401 there goes straight to redirectToLogin.
 * One shared in-flight promise per token key so N concurrent 401s
 * trigger exactly one refresh call, not N. */
const refreshInFlight: Partial<Record<string, Promise<string>>> = {};

function refreshTokenKeyFor(tokenKey: string): string {
  return tokenKey === "cps_platform_access" ? "cps_platform_refresh" : "cps_refresh";
}

async function refreshAccessToken(tokenKey: string): Promise<string> {
  if (tokenKey !== "cps_access") throw new Error("no refresh endpoint for this realm");
  const existing = refreshInFlight[tokenKey];
  if (existing) return existing;

  const attempt = (async () => {
    const refreshValue = window.localStorage.getItem(refreshTokenKeyFor(tokenKey));
    if (!refreshValue) throw new Error("no refresh token stored");
    const res = await fetch(`${API_BASE}/auth/refresh/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh: refreshValue }),
    });
    if (!res.ok) throw new Error("refresh call failed");
    const data = (await res.json()) as { access: string };
    window.localStorage.setItem(tokenKey, data.access);
    return data.access;
  })();

  refreshInFlight[tokenKey] = attempt;
  try {
    return await attempt;
  } finally {
    delete refreshInFlight[tokenKey];
  }
}

/** Clears this realm's stored tokens and hard-navigates to its login
 * screen — a full navigation (not client-side routing) since this is a
 * plain module, not a React component, and the whole point is to leave
 * whatever screen was open when the session died. The query param is
 * how the login page knows to show t("sessionExpired") instead of its
 * normal empty state — never the raw backend body (SimpleJWT's own
 * bundled Arabic translation for "token" is "تأشيرة", a real, wrong,
 * upstream-package mistranslation this app must never surface). */
function redirectToLogin(tokenKey: string) {
  if (typeof window === "undefined") return;
  if (tokenKey === "cps_platform_access") {
    window.localStorage.removeItem("cps_platform_access");
    window.localStorage.removeItem("cps_platform_refresh");
    window.localStorage.removeItem("cps_platform_user");
    window.location.href = "/platform/login?session_expired=1";
  } else {
    window.localStorage.removeItem("cps_access");
    window.localStorage.removeItem("cps_refresh");
    window.localStorage.removeItem("cps_user");
    window.localStorage.removeItem("cps_tenant");
    window.location.href = "/login?session_expired=1";
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  auth = true,
  tokenKey = "cps_access",
  isRetry = false
): Promise<T> {
  const headers = new Headers(options.headers);
  // FormData (file uploads) must NOT get a manual Content-Type — the
  // browser sets "multipart/form-data; boundary=..." itself, and
  // overriding it here would drop the boundary and break parsing.
  if (!(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  // Backend messages (validation errors, etc.) are translated per the
  // active Django language, chosen from this header — tied to the
  // app's own ar/en toggle so error text always matches the UI
  // language, instead of guessing from the browser's own Accept-Language.
  headers.set("Accept-Language", getLocale());
  if (auth) {
    const token = getAccessToken(tokenKey);
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

  // Sprint 6.5.10 (UAT note 7): a 401 on an authenticated call means
  // the access token itself expired mid-session — never shown to the
  // user as a form error (see fieldErrors' reserved-key skip below for
  // the defense-in-depth side of this same bug). Try one silent
  // refresh-and-retry; only redirect to login if that also fails.
  // `auth=false` calls (login/register/refresh itself) are never
  // retried — a 401 there is a real "wrong credentials", not a expiry.
  if (res.status === 401 && auth && !isRetry) {
    try {
      await refreshAccessToken(tokenKey);
      return await request<T>(path, options, auth, tokenKey, true);
    } catch {
      redirectToLogin(tokenKey);
      return new Promise<T>(() => {}); // navigation is already underway
    }
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

// Sprint 6.5.10 (UAT note 6): never real field names in this codebase
// — "detail"/"code" are DRF's/SimpleJWT's own generic-error keys
// (e.g. {"detail": "Token is invalid or expired", "code":
// "token_not_valid"} on a 401), and "non_field_errors" is what
// generalError() already reads separately. Without this, a 401/403
// whose body happens to include "code" would attach its message to
// any FormField literally named "code" (tax codes, chart of accounts,
// cost centers, assets, …) — exactly the "token_not_valid under the
// كود field" bug this fixes.
const RESERVED_ERROR_KEYS = new Set(["detail", "code", "non_field_errors"]);

/** DRF's standard error shape: {field: [msg, ...]} plus optionally
 * non_field_errors / detail. Never assume it — the server can also
 * return a flat {detail: "..."} for auth/permission errors. */
export function fieldErrors(body: unknown): Record<string, string> {
  if (!body || typeof body !== "object") return {};
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(body as Record<string, unknown>)) {
    if (RESERVED_ERROR_KEYS.has(key)) continue;
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
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  /** multipart/form-data POST — sprint 5.1/5.2 attachment uploads. */
  upload: <T>(path: string, formData: FormData) => request<T>(path, { method: "POST", body: formData }),
};

/** Same request/error handling as `api`, but reads its bearer token from
 * "cps_platform_access" instead of "cps_access" — sprint 2's platform
 * admin panel has its own, cryptographically separate auth realm
 * (apps/platform/auth.py on the backend), so it must never share a
 * token with the customer-facing `api` above. */
export const platformApi = {
  get: <T>(path: string) => request<T>(path, { method: "GET" }, true, "cps_platform_access"),
  post: <T>(path: string, body?: unknown, auth = true) =>
    request<T>(
      path,
      { method: "POST", body: body ? JSON.stringify(body) : undefined },
      auth,
      "cps_platform_access"
    ),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(
      path,
      { method: "PATCH", body: body ? JSON.stringify(body) : undefined },
      true,
      "cps_platform_access"
    ),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }, true, "cps_platform_access"),
};
