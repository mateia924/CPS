"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { ApiError } from "@/lib/api";
import { useLocale } from "@/lib/i18n";

// Block 8.0.1: the 8.0 live walk opened purchasing settings as a role
// without purchasing.view and got an empty main area — the page's
// `api.get(...).then(set)` rejected with a 403 nobody caught, the page
// stayed on its `if (!data) return null`, and nothing said why. Most
// screens load the same way (and DataTable's own load has no catch), so
// the fix is here, once, not per screen: a 403 that reached no handler
// of the screen's own surfaces as an "unhandledrejection", and the shell
// turns it into a named state for the screen that raised it. A screen
// that catches its own 403 (a form's save, the inbox count) keeps its
// own message; this never sees it.
//
// The children still render: a screen whose main request worked but one
// side request was refused keeps working, with this notice above it.
// Navigating to another screen clears it.
export function ScreenAccess({ children }: { children: React.ReactNode }) {
  const { t } = useLocale();
  const pathname = usePathname();
  const [forbiddenAt, setForbiddenAt] = useState<string | null>(null);

  useEffect(() => {
    const onUnhandled = (event: PromiseRejectionEvent) => {
      if (event.reason instanceof ApiError && event.reason.status === 403) {
        event.preventDefault();
        setForbiddenAt(window.location.pathname);
      }
    };
    window.addEventListener("unhandledrejection", onUnhandled);
    return () => window.removeEventListener("unhandledrejection", onUnhandled);
  }, []);

  return (
    <>
      {forbiddenAt === pathname && (
        <div className="card" role="alert" data-state="forbidden" style={{ borderColor: "var(--danger)" }}>
          <h2 style={{ marginTop: 0 }}>{t("noPermissionTitle")}</h2>
          <p style={{ marginBottom: 0 }}>{t("noPermissionBody")}</p>
        </div>
      )}
      {children}
    </>
  );
}
