"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { ApiError } from "@/lib/api";
import { useLocale } from "@/lib/i18n";

// Block 8.0.1 named the 403. Block 8.0.2: the same for every failure a
// screen does not handle itself. The 8.0.1 walk found an API 404 and a JSON
// 500 leaving a blank main area, and — the serious one — an HTML 500 on a
// list rendering as «لا توجد بيانات لعرضها»: a server failure told the
// accountant there are zero records. A blank screen at least looks wrong;
// "no data" asserts the opposite of what happened.

export type ApiErrorKind = "forbidden" | "not-found" | "server-error" | "network";

/** Which named state an ApiError gets, or null for the statuses a screen
 * answers itself (400 field errors, 409 conflicts, 401 handled by the
 * client's refresh-and-retry). 0 = no HTTP response at all. */
export function apiErrorKind(error: unknown): ApiErrorKind | null {
  if (!(error instanceof ApiError)) return null;
  if (error.status === 403) return "forbidden";
  if (error.status === 404) return "not-found";
  if (error.status === 0) return "network";
  if (error.status >= 500) return "server-error";
  return null;
}

const TEXT: Record<ApiErrorKind, { title: string; body: string }> = {
  forbidden: { title: "noPermissionTitle", body: "noPermissionBody" },
  "not-found": { title: "errorNotFoundTitle", body: "errorNotFoundBody" },
  "server-error": { title: "errorServerTitle", body: "errorServerBody" },
  network: { title: "errorNetworkTitle", body: "errorNetworkBody" },
};

/** The named state itself — the shell's card, and DataTable's row. The
 * data-state value is what tests and walks look for. */
export function ErrorState({ kind, compact = false }: { kind: ApiErrorKind; compact?: boolean }) {
  const { t } = useLocale();
  const text = TEXT[kind];
  return (
    <div
      className={compact ? undefined : "card"}
      role="alert"
      data-state={kind}
      style={compact ? { padding: "1rem", textAlign: "center" } : { borderColor: "var(--danger)" }}
    >
      {compact ? <strong>{t(text.title)}</strong> : <h2 style={{ marginTop: 0 }}>{t(text.title)}</h2>}
      <p style={{ marginBottom: 0 }}>{t(text.body)}</p>
    </div>
  );
}

/** Mounted by the dashboard layout around every screen. An ApiError that
 * reached no handler of the screen's own surfaces as "unhandledrejection";
 * the shell shows its named state for the screen that raised it. The
 * children still render — a screen whose main request worked keeps working
 * under the notice. Navigating away clears it. */
export function ScreenErrors({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [failure, setFailure] = useState<{ path: string; kind: ApiErrorKind } | null>(null);

  useEffect(() => {
    const onUnhandled = (event: PromiseRejectionEvent) => {
      const kind = apiErrorKind(event.reason);
      if (kind) {
        event.preventDefault();
        // The first failure on a screen names it: a 403 is not overwritten
        // by a 500 from a later side request, and vice versa.
        setFailure((prev) => (prev && prev.path === window.location.pathname ? prev : { path: window.location.pathname, kind }));
      }
    };
    window.addEventListener("unhandledrejection", onUnhandled);
    return () => window.removeEventListener("unhandledrejection", onUnhandled);
  }, []);

  return (
    <>
      {failure && failure.path === pathname && <ErrorState kind={failure.kind} />}
      {children}
    </>
  );
}
