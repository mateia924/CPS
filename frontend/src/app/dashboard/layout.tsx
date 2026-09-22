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
  // there's nothing to manage until they add a second entity. Sprint
  // 3.5 (3.18): the same gate now also hides "الشركات الشقيقة" and the
  // advanced "الأطراف (عرض شامل)" screen — neither makes sense for a
  // single-branch tenant either.
  const showOrganization = !!me && !me.simplified_mode && me.features.organization;
  const showCostCenters = !!me && me.features.cost_centers && me.permissions.includes("costcenters.view");
  const showAffiliates = !!me && !me.simplified_mode;
  const showRoles = !!me && me.permissions.includes("roles.manage");
  const showFullPartiesView =
    !!me && !me.simplified_mode && me.permissions.includes("parties.view_all");
  // Sprint 3 (3.13): Free hides both; Business+ shows them.
  const showTreasury = !!me && me.features.treasury;
  const showAssets = !!me && me.features.assets;
  // Sprint 3.5 (3.18): "المشتريات ... purchasing".
  const showPurchasing = !!me && me.features.purchasing;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <h2>{tenant?.name}</h2>
        <Link href="/dashboard">{t("dashboard")}</Link>

        <div className="sidebar-section-label">{t("salesSection")}</div>
        <Link href="/dashboard/customers">{t("customers")}</Link>
        <Link href="/dashboard/products">{t("products")}</Link>
        <Link href="/dashboard/invoices">{t("invoices")}</Link>

        {showPurchasing && (
          <>
            <div className="sidebar-section-label">{t("purchasingSection")}</div>
            <Link href="/dashboard/suppliers">{t("suppliers")}</Link>
          </>
        )}

        {showTreasury && (
          <>
            <div className="sidebar-section-label">{t("treasurySection")}</div>
            <Link href="/dashboard/treasury/banks">{t("banks")}</Link>
            <Link href="/dashboard/treasury/cash-boxes">{t("cashBoxes")}</Link>
            <Link href="/dashboard/treasury/custodies">{t("custodies")}</Link>
          </>
        )}

        {showAssets && (
          <>
            <div className="sidebar-section-label">{t("assetsSection")}</div>
            <Link href="/dashboard/assets">{t("assets")}</Link>
          </>
        )}

        <div className="sidebar-section-label">{t("hrSection")}</div>
        <Link href="/dashboard/employees">{t("employeesNav")}</Link>

        {(showOrganization || showCostCenters || showAffiliates || showRoles || showFullPartiesView) && (
          <div className="sidebar-section-label">{t("settingsSection")}</div>
        )}
        {showOrganization && <Link href="/dashboard/organization">{t("organization")}</Link>}
        {showCostCenters && <Link href="/dashboard/cost-centers">{t("costCenters")}</Link>}
        {showAffiliates && <Link href="/dashboard/affiliates">{t("affiliatesNav")}</Link>}
        {showRoles && <Link href="/dashboard/roles">{t("rolesAndUsers")}</Link>}
        {showFullPartiesView && (
          <Link href="/dashboard/settings/parties">{t("fullPartiesView")}</Link>
        )}

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
