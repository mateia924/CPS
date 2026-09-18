"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { usePlatformAuth } from "@/lib/platform-auth-context";
import { useLocale } from "@/lib/i18n";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";

export default function PlatformDashboardLayout({ children }: { children: React.ReactNode }) {
  const { user, isReady, logout } = usePlatformAuth();
  const { t } = useLocale();
  const router = useRouter();

  useEffect(() => {
    if (isReady && !user) {
      router.replace("/platform/login");
    }
  }, [isReady, user, router]);

  if (!isReady || !user) return null;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <h2>{t("platformTitle")}</h2>
        <Link href="/platform/dashboard/tenants">{t("tenants")}</Link>
        <Link href="/platform/dashboard/audit-log">{t("auditLog")}</Link>
        <div style={{ marginTop: "auto", paddingTop: "1rem" }}>
          <p style={{ fontSize: "0.85rem", color: "var(--muted)" }}>
            {user.full_name} — {user.role}
          </p>
          <LocaleSwitcher />
          <button
            className="secondary"
            style={{ marginTop: "0.5rem", width: "100%" }}
            onClick={() => {
              logout();
              router.replace("/platform/login");
            }}
          >
            {t("logout")}
          </button>
        </div>
      </aside>
      <main className="main-content">{children}</main>
    </div>
  );
}
