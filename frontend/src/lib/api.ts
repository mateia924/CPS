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

// Sprint 6.5.14 item 7: a non-JSON API response (Django's own bare 500
// page, an nginx 502/504 HTML page, or an empty body on a failing
// status) must never reach a screen as raw text — one unified message,
// on every screen that calls generalError(), not just login. Kept here
// rather than in lib/i18n.tsx: this file has no React context to read
// the active locale from, and every existing sentinel (network_error)
// already resolves through the same plain getLocale() below.
const SERVER_ERROR_MESSAGE: Record<string, string> = {
  ar: "خطأ في الخادم — حاول مرة أخرى بعد قليل",
  en: "Server error — please try again shortly.",
};

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
  let nonJson = false;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      // Non-JSON body — Django's own bare 500 page, or an nginx/proxy
      // error page (502/504 HTML), never DRF's JSON error shape. The
      // raw text stays in the browser console for a developer to read
      // (sprint 6.5.14 item 7: no screen may ever render it) — see
      // generalError()'s "non_json_response" sentinel below.
      console.error("Non-JSON API response", res.status, text.slice(0, 500));
      nonJson = true;
    }
  }

  if (!res.ok) {
    // Sprint 6.5.14 item 7: an empty body on a failing response (some
    // 502/504s send none at all) is exactly as unrecoverable to a real
    // user as a non-empty HTML one — same sentinel either way.
    throw new ApiError(res.status, nonJson || data === null ? { detail: "non_json_response" } : data);
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

// Sprint 6.5.15 (UAT item 4): a handful of fields are only ever
// rendered inside a collapsed <details> ("متقدم") in some screens —
// FormField still receives the error prop and the [data-field] element
// still exists, but a closed <details> gives it no layout box at all,
// so the message is technically "shown" yet invisible (the exact live
// bug: legal_entity on a treasury account form, 400 body correctly
// carrying {"legal_entity": [...]}, user sees only "تعذّر الحفظ."). A
// field genuinely absent from this screen's form entirely has the same
// problem. Checked against the live DOM rather than a per-screen list
// so every screen is covered automatically, with zero per-screen
// plumbing — this file has no React context, but `document` is always
// available client-side by the time a submit's catch block runs.
function isFieldVisible(name: string): boolean {
  if (typeof document === "undefined") return false;
  const el = document.querySelector(`[data-field="${name}"]`);
  if (!el) return false;
  // A closed <details> ("متقدم") clips its content via the ANCESTOR
  // <details> box, not by shrinking the field's own box — offsetParent,
  // getClientRects() and even the field's own getBoundingClientRect()
  // all still report it as if unclipped (only the ancestor is
  // collapsed). checkVisibility() is the one API built to answer "can
  // the user actually see this," walking every ancestor's display/
  // visibility/content-visibility for exactly this case.
  if (typeof (el as { checkVisibility?: () => boolean }).checkVisibility === "function") {
    return (el as unknown as { checkVisibility: (opts?: object) => boolean }).checkVisibility({
      checkOpacity: true, checkVisibilityCSS: true,
    });
  }
  const rect = el.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}

const FIELD_LABELS: Record<string, Record<string, string>> = {
  legal_entity: { ar: "الشركة / الفرع", en: "Company / Branch" },
};

/** A single message to show when there's no better field to attach the
 * error to (network failure, {detail: "..."}, or an unrecognized shape).
 *
 * Sprint 6.5.18 (UAT item 6): a 6.5.10-era regression left this
 * function only ever returning `obj.detail` when it was a plain
 * string — DRF wraps a raised `ValidationError({"detail": [...]})`
 * (the shape apps.vouchers.services._balance_warnings_and_checks uses
 * for "رصيد حساب الخزينة لا يكفي...") in a *list*, so that message was
 * silently swallowed down to `fallback` on every screen, for every
 * status code. Fixed to read `detail` as either shape — except on a
 * 401/403, where `detail` is DRF's/SimpleJWT's own generic, English,
 * not-written-for-end-users text ("Token is invalid...", "You do not
 * have permission..."), which should keep falling back to this
 * screen's own contextual message instead. */
export function generalError(body: unknown, fallback: string, status?: number): string {
  if (!body || typeof body !== "object") return fallback;
  const obj = body as Record<string, unknown>;
  if (obj.detail === "network_error") return fallback;
  if (obj.detail === "non_json_response") return SERVER_ERROR_MESSAGE[getLocale()] ?? SERVER_ERROR_MESSAGE.ar;

  const unmatched: string[] = [];
  for (const [key, value] of Object.entries(obj)) {
    if (RESERVED_ERROR_KEYS.has(key) || isFieldVisible(key)) continue;
    const message = Array.isArray(value) ? value.map(String).join(" ") : typeof value === "string" ? value : null;
    if (message !== null) unmatched.push(`${FIELD_LABELS[key]?.[getLocale()] ?? key}: ${message}`);
  }
  if (unmatched.length > 0) return unmatched.join(" — ");

  if (status !== 401 && status !== 403) {
    if (typeof obj.detail === "string") return obj.detail;
    if (Array.isArray(obj.detail)) return obj.detail.map(String).join(" ");
  }
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
