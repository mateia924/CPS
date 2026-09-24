"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import type { PendingApproval } from "@/lib/types";

// BRAND.md §4 "الشريط الجانبي": the active item gets a filled background
// plus a --sidebar-active-bar stripe on the leading edge.
function SidebarLink({ href, children }: { href: string; children: React.ReactNode }) {
  const pathname = usePathname();
  const active = pathname === href || pathname.startsWith(`${href}/`);
  return (
    <Link href={href} className={active ? "active" : undefined}>
      {children}
    </Link>
  );
}

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
  const showVouchers = showTreasury && !!me && me.permissions.includes("vouchers.view");
  const showCompanySettings = !!me && me.permissions.includes("organization.manage");
  const showAssets = !!me && me.features.assets;
  // Sprint 3.5 (3.18): "المشتريات ... purchasing".
  const showPurchasing = !!me && me.features.purchasing;
  const showAccounting = !!me && me.permissions.includes("accounting.view");
  const showApprovalRules = !!me && me.permissions.includes("approvals.view");
  const showDocumentNumbering = !!me && me.permissions.includes("numbering.view");
  // Sprint 6.1 (decision 1): fiscal years/periods management screen —
  // gated by the "manage" permission, same pattern as company settings.
  const showFiscalYears = !!me && me.permissions.includes("accounting.manage_fiscal_periods");
  // Sprint 6.0.1-B: the inbox aggregates every approvable doc_type
  // (apps.approvals.views.PendingApprovalsView) — no single RBAC
  // permission covers all of them, so this reuses the same permission
  // codes those doc types' own "approve" actions already require
  // (apps.sales/vouchers/accounting/treasury.views permission_map) —
  // "does this user hold an approval permission for anything at all".
  const showApprovalInbox =
    !!me &&
    (me.permissions.includes("invoices.approve") ||
      me.permissions.includes("vouchers.approve") ||
      me.permissions.includes("accounting.manage") ||
      me.permissions.includes("treasury.request_iban_change"));

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <img
          src="/brand/cps-logo-stacked-compact-white.svg"
          alt="CPS"
          style={{ width: 120, display: "block", marginBottom: "0.5rem" }}
        />
        <h2 style={{ margin: "0 0 0.75rem", fontSize: "0.95rem", fontWeight: 500, color: "var(--sidebar-text)" }}>
          {tenant?.name}
        </h2>
        {meError && (
          // Sprint 4.8: /me failing must never look like "this tenant
          // just has fewer permissions" — a visible, explicit error
          // instead of a silently truncated menu (permission/feature
          // -gated sections below all evaluate to false when `me` is
          // null, which is otherwise indistinguishable from a real,
          // intentionally limited menu).
          <div
            className="card"
            style={{ padding: "0.6rem 0.75rem", marginBottom: "0.75rem", borderColor: "var(--danger)" }}
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
        {showApprovalInbox && (
        <div className="topbar" style={{ marginBottom: "0.5rem" }}>
          <Link href="/dashboard/approvals" style={{ color: "var(--sidebar-text)" }}>
            {t("approvalInbox")}
            {pendingCount > 0 && (
              <span
                style={{
                  marginInlineStart: "0.4rem",
                  background: "var(--danger)",
                  color: "var(--color-on-primary)",
                  borderRadius: "var(--radius-pill)",
                  padding: "0.05rem 0.5rem",
                  fontSize: "0.75rem",
                }}
              >
                {pendingCount}
              </span>
            )}
          </Link>
        </div>
        )}
        <SidebarLink href="/dashboard">{t("dashboard")}</SidebarLink>

        <div className="sidebar-section-label">{t("salesSection")}</div>
        <SidebarLink href="/dashboard/customers">{t("customers")}</SidebarLink>
        <SidebarLink href="/dashboard/products">{t("products")}</SidebarLink>
        <SidebarLink href="/dashboard/invoices">{t("invoices")}</SidebarLink>

        {showPurchasing && (
          <>
            <div className="sidebar-section-label">{t("purchasingSection")}</div>
            <SidebarLink href="/dashboard/suppliers">{t("suppliers")}</SidebarLink>
          </>
        )}

        {showTreasury && (
          <>
            <div className="sidebar-section-label">{t("treasurySection")}</div>
            <SidebarLink href="/dashboard/treasury/banks">{t("banks")}</SidebarLink>
            <SidebarLink href="/dashboard/treasury/cash-boxes">{t("cashBoxes")}</SidebarLink>
            <SidebarLink href="/dashboard/treasury/custodies">{t("custodies")}</SidebarLink>
            {showVouchers && (
              <>
                <SidebarLink href="/dashboard/treasury/vouchers/receipt">{t("receiptVouchers")}</SidebarLink>
                <SidebarLink href="/dashboard/treasury/vouchers/payment">{t("paymentVouchers")}</SidebarLink>
                <SidebarLink href="/dashboard/treasury/vouchers/settlement">{t("settlementVouchers")}</SidebarLink>
              </>
            )}
            <SidebarLink href="/dashboard/treasury/exchange-rates">{t("exchangeRatesNav")}</SidebarLink>
          </>
        )}

        {showAccounting && (
          <>
            <div className="sidebar-section-label">{t("accountingSection")}</div>
            <SidebarLink href="/dashboard/accounting/chart-of-accounts">{t("chartOfAccounts")}</SidebarLink>
            <SidebarLink href="/dashboard/accounting/journal-entries">{t("manualJournalEntries")}</SidebarLink>
            <SidebarLink href="/dashboard/accounting/opening-balances">{t("openingBalancesNav")}</SidebarLink>
            <SidebarLink href="/dashboard/accounting/recurring-entries">{t("recurringEntriesNav")}</SidebarLink>
            <SidebarLink href="/dashboard/accounting/tax-codes">{t("taxCodesNav")}</SidebarLink>
            <SidebarLink href="/dashboard/accounting/tax-periods">{t("taxPeriodsNav")}</SidebarLink>
          </>
        )}

        {showAccounting && (
          <>
            <div className="sidebar-section-label">{t("reportsSection")}</div>
            <SidebarLink href="/dashboard/reports/trial-balance">{t("trialBalanceNav")}</SidebarLink>
            <SidebarLink href="/dashboard/reports/ledger">{t("ledgerNav")}</SidebarLink>
            <SidebarLink href="/dashboard/reports/statement">{t("statementReportNav")}</SidebarLink>
          </>
        )}

        {showAssets && (
          <>
            <div className="sidebar-section-label">{t("assetsSection")}</div>
            <SidebarLink href="/dashboard/assets">{t("assets")}</SidebarLink>
          </>
        )}

        <div className="sidebar-section-label">{t("hrSection")}</div>
        <SidebarLink href="/dashboard/employees">{t("employeesNav")}</SidebarLink>

        {(showOrganization ||
          showCostCenters ||
          showAffiliates ||
          showRoles ||
          showFullPartiesView ||
          showApprovalRules ||
          showDocumentNumbering ||
          showFiscalYears ||
          showCompanySettings) && <div className="sidebar-section-label">{t("settingsSection")}</div>}
        {showCompanySettings && <SidebarLink href="/dashboard/settings/company">{t("companySettingsNav")}</SidebarLink>}
        {showOrganization && <SidebarLink href="/dashboard/organization">{t("organization")}</SidebarLink>}
        {showCostCenters && <SidebarLink href="/dashboard/cost-centers">{t("costCenters")}</SidebarLink>}
        {showAffiliates && <SidebarLink href="/dashboard/affiliates">{t("affiliatesNav")}</SidebarLink>}
        {showRoles && <SidebarLink href="/dashboard/roles">{t("rolesAndUsers")}</SidebarLink>}
        {showFullPartiesView && (
          <SidebarLink href="/dashboard/settings/parties">{t("fullPartiesView")}</SidebarLink>
        )}
        {showApprovalRules && (
          <SidebarLink href="/dashboard/settings/approval-rules">{t("approvalRulesNav")}</SidebarLink>
        )}
        {showDocumentNumbering && (
          <SidebarLink href="/dashboard/settings/document-numbering">{t("documentNumberingNav")}</SidebarLink>
        )}
        {showFiscalYears && (
          <SidebarLink href="/dashboard/settings/fiscal-years">{t("fiscalYearsNav")}</SidebarLink>
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
      <main className="main-content">
        {tenant?.status === "past_due" && (
          <div className="banner-warning" role="alert">
            {t("pastDueWarning")}
          </div>
        )}
        {children}
      </main>
    </div>
  );
}
