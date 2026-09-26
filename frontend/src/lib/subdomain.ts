// Sprint 6.9.1 (item I, decision 7): the one place that knows how to
// turn the browser's own hostname into a tenant subdomain (or decide
// the host carries none) — the login screen is the only caller today,
// but this stays separate from it so a second caller never has to
// re-derive the same rule.

const APP_DOMAIN_HOST = (process.env.NEXT_PUBLIC_APP_DOMAIN || "localhost:3000").split(":")[0];

const LAST_SUBDOMAIN_KEY = "cps.lastSubdomain";

const IPV4_PATTERN = /^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$/;

/** The label in front of NEXT_PUBLIC_APP_DOMAIN in `hostname`, or null
 * when the host carries no company identifier at all — the bare app
 * domain itself, "localhost", or a raw IP (this dev host's own
 * address, never a real subdomain). */
export function subdomainFromHostname(hostname: string): string | null {
  if (!hostname || hostname === APP_DOMAIN_HOST || hostname === "localhost" || IPV4_PATTERN.test(hostname)) {
    return null;
  }
  const suffix = `.${APP_DOMAIN_HOST}`;
  if (!hostname.endsWith(suffix)) return null;
  const label = hostname.slice(0, -suffix.length);
  return label || null;
}

export function rememberSubdomain(subdomain: string) {
  try {
    window.localStorage.setItem(LAST_SUBDOMAIN_KEY, subdomain);
  } catch {
    // Private window / blocked storage — the field just won't
    // pre-fill next time, never a hard failure.
  }
}

export function lastRememberedSubdomain(): string | null {
  try {
    return window.localStorage.getItem(LAST_SUBDOMAIN_KEY);
  } catch {
    return null;
  }
}
