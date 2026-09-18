"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { user, tenant, me, isReady, logout } = useAuth();
  const { t } = useLocale();
  const router = useRouter();

  useEffect(() => {
    if (isReady && !user) {
      router.replace("/login");
    }
  }, [isReady, user, router]);

  if (!isReady || !user) return null;

  // 3.13: a tenant in simplified mode never sees the organization
  // structure at all, even if they technically hold the permission —
  // there's nothing to manage until they add a second entity.
  const showOrganization = !!me && !me.simplified_mode && me.features.organization;
  const showCostCenters = !!me && me.features.cost_centers && me.permissions.includes("costcenters.view");
  const showRoles = !!me && me.permissions.includes("roles.manage");

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <h2>{tenant?.name}</h2>
        <Link href="/dashboard">{t("dashboard")}</Link>
        <Link href="/dashboard/customers">{t("customers")}</Link>
        <Link href="/dashboard/products">{t("products")}</Link>
        <Link href="/dashboard/invoices">{t("invoices")}</Link>
        {showOrganization && <Link href="/dashboard/organization">{t("organization")}</Link>}
        {showCostCenters && <Link href="/dashboard/cost-centers">{t("costCenters")}</Link>}
        {showRoles && <Link href="/dashboard/roles">{t("rolesAndUsers")}</Link>}
        <div style={{ marginTop: "auto", paddingTop: "1rem" }}>
          <LocaleSwitcher />
          <button
            className="secondary"
            style={{ marginTop: "0.5rem", width: "100%" }}
            onClick={() => {
              logout();
              router.replace("/login");
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
