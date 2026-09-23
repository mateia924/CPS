"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import type { PendingApproval } from "@/lib/types";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { user, tenant, me, meError, isReady, logout, refreshMe } = useAuth();
  const { t } = useLocale();
  const router = useRouter();
  const [pendingCount, setPendingCount] = useState(0);

  useEffect(() => {
    if (isReady && !user) {
      router.replace("/login");
    }
  }, [isReady, user, router]);

  useEffect(() => {
    if (!user) return;
    api
      .get<PendingApproval[]>("/approvals/pending/")
      .then((rows) => setPendingCount(rows.length))
      .catch(() => undefined);
  }, [user]);

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
  const showAccounting = !!me && me.permissions.includes("accounting.view");
  const showApprovalRules = !!me && me.permissions.includes("approvals.view");
  const showDocumentNumbering = !!me && me.permissions.includes("numbering.view");

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <h2>{tenant?.name}</h2>
        {meError && (
          // Sprint 4.8: /me failing must never look like "this tenant
          // just has fewer permissions" — a visible, explicit error
          // instead of a silently truncated menu (permission/feature
          // -gated sections below all evaluate to false when `me` is
          // null, which is otherwise indistinguishable from a real,
          // intentionally limited menu).
          <div
            className="card"
            style={{ padding: "0.6rem 0.75rem", marginBottom: "0.75rem", borderColor: "#a3492f" }}
          >
            <p style={{ margin: 0, fontSize: "0.85rem" }}>{meError}</p>
            <button
              type="button"
              className="secondary"
              style={{ marginTop: "0.4rem" }}
              onClick={() => refreshMe()}
            >
              {t("retry")}
            </button>
          </div>
        )}
        <div className="topbar" style={{ marginBottom: "0.5rem" }}>
          <Link href="/dashboard/approvals">
            {t("approvalInbox")}
            {pendingCount > 0 && (
              <span
                style={{
                  marginInlineStart: "0.4rem",
                  background: "#a3492f",
                  color: "#fff",
                  borderRadius: "999px",
                  padding: "0.05rem 0.5rem",
                  fontSize: "0.75rem",
                }}
              >
                {pendingCount}
              </span>
            )}
          </Link>
        </div>
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
            <Link href="/dashboard/treasury/exchange-rates">{t("exchangeRatesNav")}</Link>
          </>
        )}

        {showAccounting && (
          <>
            <div className="sidebar-section-label">{t("accountingSection")}</div>
            <Link href="/dashboard/accounting/chart-of-accounts">{t("chartOfAccounts")}</Link>
            <Link href="/dashboard/accounting/journal-entries">{t("manualJournalEntries")}</Link>
            <Link href="/dashboard/accounting/tax-codes">{t("taxCodesNav")}</Link>
            <Link href="/dashboard/accounting/tax-periods">{t("taxPeriodsNav")}</Link>
          </>
        )}

        {showAccounting && (
          <>
            <div className="sidebar-section-label">{t("reportsSection")}</div>
            <Link href="/dashboard/reports/trial-balance">{t("trialBalanceNav")}</Link>
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

        {(showOrganization ||
          showCostCenters ||
          showAffiliates ||
          showRoles ||
          showFullPartiesView ||
          showApprovalRules ||
          showDocumentNumbering) && <div className="sidebar-section-label">{t("settingsSection")}</div>}
        {showOrganization && <Link href="/dashboard/organization">{t("organization")}</Link>}
        {showCostCenters && <Link href="/dashboard/cost-centers">{t("costCenters")}</Link>}
        {showAffiliates && <Link href="/dashboard/affiliates">{t("affiliatesNav")}</Link>}
        {showRoles && <Link href="/dashboard/roles">{t("rolesAndUsers")}</Link>}
        {showFullPartiesView && (
          <Link href="/dashboard/settings/parties">{t("fullPartiesView")}</Link>
        )}
        {showApprovalRules && (
          <Link href="/dashboard/settings/approval-rules">{t("approvalRulesNav")}</Link>
        )}
        {showDocumentNumbering && (
          <Link href="/dashboard/settings/document-numbering">{t("documentNumberingNav")}</Link>
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
