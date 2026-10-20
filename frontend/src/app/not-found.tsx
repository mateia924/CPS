"use client";

import Link from "next/link";
import { useLocale } from "@/lib/i18n";

/** Block 8.0.2: an unknown URL used to get Next's default page — English,
 * outside the app's look, "404 This page could not be found." The same
 * named not-found state the dashboard uses, in the app's own words. */
export default function NotFound() {
  const { t } = useLocale();
  return (
    <main style={{ maxWidth: 560, margin: "4rem auto", padding: "0 1rem" }}>
      <div className="card" role="alert" data-state="not-found" style={{ borderColor: "var(--danger)" }}>
        <h2 style={{ marginTop: 0 }}>{t("errorNotFoundTitle")}</h2>
        <p>{t("errorPageNotFound")}</p>
        <Link href="/dashboard">{t("errorBackToDashboard")}</Link>
      </div>
    </main>
  );
}
