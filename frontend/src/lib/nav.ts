import type { MeResponse } from "./types";

// Block 8.0.1: the sidebar as data. The 8.0 live walk found links to
// screens the user could not open (purchasing settings for a role
// without purchasing.view: the link showed, the screen 403'd). Every
// entry now has to say which permission its screen's API requires — the
// type makes "neither" a compile error — or name, in words, why it has
// none. The permission is the one the backend enforces on the screen's
// own list endpoint (permission_map), not a guess from the label.
//
// `when` keeps the non-permission gates the sidebar already had (module
// feature flags, simplified mode). A section with no visible entry
// renders no heading.

type Me = MeResponse;

export type NavGate =
  // Any one of these codes is enough (the approval inbox's case).
  | { permission: string | readonly string[]; ungated?: never }
  // The reason this screen needs no permission at all.
  | { ungated: string; permission?: never };

export type NavEntry = NavGate & {
  href: string;
  label: string | ((me: Me) => string);
  when?: (me: Me) => boolean;
};

export type NavSection = {
  label?: string;
  when?: (me: Me) => boolean;
  entries: NavEntry[];
};

export function hasPermission(me: Me | null, gate: NavGate): boolean {
  if (gate.ungated !== undefined) return true;
  if (!me) return false;
  const codes = typeof gate.permission === "string" ? [gate.permission] : gate.permission;
  return codes.some((code) => me.permissions.includes(code));
}

export function canSee(me: Me | null, entry: NavEntry, section?: NavSection): boolean {
  if (!hasPermission(me, entry)) return false;
  if (section?.when && (!me || !section.when(me))) return false;
  if (entry.when && (!me || !entry.when(me))) return false;
  return true;
}

// The approval inbox sits in the top bar with its pending-count badge,
// not in a section. Same gate shape, same check. Sprint 6.0.1-B: no
// single permission covers every approvable doc_type, so it is "holds
// an approve permission for anything at all".
export const APPROVAL_INBOX: NavEntry = {
  href: "/dashboard/approvals",
  label: "approvalInbox",
  permission: ["invoices.approve", "vouchers.approve", "accounting.manage", "treasury.request_iban_change"],
};

export const PROFILE: NavEntry = {
  href: "/dashboard/profile",
  label: "profileNav",
  ungated: "the user's own account: password, 2FA, notifications",
};

export const NAV_SECTIONS: NavSection[] = [
  {
    entries: [
      { href: "/dashboard", label: "dashboard", ungated: "landing page; /dashboard/summary/ only needs a login" },
    ],
  },
  {
    label: "salesSection",
    entries: [
      { href: "/dashboard/customers", label: "customers", permission: "parties.view" },
      { href: "/dashboard/products", label: "items", permission: "products.view" },
      { href: "/dashboard/invoices", label: "invoices", permission: "invoices.view" },
    ],
  },
  {
    // Sprint 3.5 (3.18): "المشتريات ... purchasing".
    label: "purchasingSection",
    when: (me) => me.features.purchasing,
    entries: [
      { href: "/dashboard/suppliers", label: "suppliers", permission: "parties.view" },
      { href: "/dashboard/purchasing/settings", label: "purchaseSettings", permission: "purchasing.view" },
    ],
  },
  {
    // Sprint 7.1: shown only for a tenant that has the inventory module.
    label: "inventorySection",
    when: (me) => me.features.inventory,
    entries: [
      { href: "/dashboard/inventory/stock/receipts", label: "stockReceipts", permission: "inventory.view" },
      { href: "/dashboard/inventory/stock/issues", label: "stockIssues", permission: "inventory.view" },
      { href: "/dashboard/inventory/stock/transfers", label: "stockTransfers", permission: "inventory.view" },
      { href: "/dashboard/inventory/stock/counts", label: "stockCounts", permission: "inventory.view" },
      { href: "/dashboard/inventory/balances", label: "stockBalances", permission: "inventory.view" },
      { href: "/dashboard/inventory/warehouses", label: "warehouses", permission: "inventory.view" },
      // Categories and units are `products` data (D7/D18), gated as such.
      { href: "/dashboard/inventory/item-categories", label: "itemCategories", permission: "products.view" },
      { href: "/dashboard/inventory/units", label: "unitsOfMeasure", permission: "products.view" },
      { href: "/dashboard/inventory/settings", label: "inventorySettings", permission: "inventory.view" },
    ],
  },
  {
    // Sprint 3 (3.13): Free hides treasury; Business+ shows it.
    label: "treasurySection",
    when: (me) => me.features.treasury,
    entries: [
      { href: "/dashboard/treasury/banks", label: "banks", permission: "treasury.view" },
      { href: "/dashboard/treasury/cash-boxes", label: "cashBoxes", permission: "treasury.view" },
      { href: "/dashboard/treasury/custodies", label: "custodies", permission: "treasury.view" },
      { href: "/dashboard/treasury/vouchers/receipt", label: "receiptVouchers", permission: "vouchers.view" },
      { href: "/dashboard/treasury/vouchers/payment", label: "paymentVouchers", permission: "vouchers.view" },
      { href: "/dashboard/treasury/vouchers/settlement", label: "settlementVouchers", permission: "vouchers.view" },
      { href: "/dashboard/treasury/exchange-rates", label: "exchangeRatesNav", permission: "treasury.view" },
      { href: "/dashboard/treasury/reconciliation", label: "bankReconciliationDashboardNav", permission: "treasury.view" },
    ],
  },
  {
    // 6.5.7 (§11): recurring entries follow the same gate as every other
    // accounting screen — simplified mode never hides an accounting tool.
    label: "accountingSection",
    entries: [
      { href: "/dashboard/accounting/chart-of-accounts", label: "chartOfAccounts", permission: "accounting.view" },
      { href: "/dashboard/accounting/journal-entries", label: "manualJournalEntries", permission: "accounting.view" },
      { href: "/dashboard/accounting/opening-balances", label: "openingBalancesNav", permission: "accounting.view" },
      { href: "/dashboard/accounting/recurring-entries", label: "recurringEntriesNav", permission: "accounting.view" },
      { href: "/dashboard/accounting/tax-codes", label: "taxCodesNav", permission: "accounting.view" },
      { href: "/dashboard/accounting/tax-periods", label: "taxPeriodsNav", permission: "accounting.view" },
    ],
  },
  {
    label: "reportsSection",
    entries: [
      { href: "/dashboard/reports/trial-balance", label: "trialBalanceNav", permission: "accounting.view" },
      { href: "/dashboard/reports/income-statement", label: "incomeStatementNav", permission: "accounting.view" },
      { href: "/dashboard/reports/balance-sheet", label: "balanceSheetNav", permission: "accounting.view" },
      { href: "/dashboard/reports/ledger", label: "ledgerNav", permission: "accounting.view" },
      { href: "/dashboard/reports/aging", label: "agingReportNav", permission: "accounting.view" },
      { href: "/dashboard/reports/statement", label: "statementReportNav", permission: "accounting.view" },
      { href: "/dashboard/reports/fixed-assets", label: "fixedAssetsReportNav", permission: "accounting.view" },
    ],
  },
  {
    label: "assetsSection",
    when: (me) => me.features.assets,
    entries: [{ href: "/dashboard/assets", label: "assets", permission: "assets.view" }],
  },
  {
    label: "hrSection",
    entries: [{ href: "/dashboard/employees", label: "employeesNav", permission: "parties.view" }],
  },
  {
    label: "settingsSection",
    entries: [
      { href: "/dashboard/settings/company", label: "companySettingsNav", permission: "organization.manage" },
      {
        // 3.13: simplified mode hides the organization structure — except
        // for the Owner (6.5.18 UAT item 7), whose only way out of
        // simplified mode is this screen, under a different label.
        href: "/dashboard/organization",
        label: (me) => (me.simplified_mode ? "legalStructureNav" : "organization"),
        permission: "organization.view",
        when: (me) => (!me.simplified_mode && me.features.organization) || me.roles.includes("Owner"),
      },
      {
        href: "/dashboard/cost-centers",
        label: "costCenters",
        permission: "costcenters.view",
        when: (me) => me.features.cost_centers,
      },
      // Sprint 3.5 (3.18): affiliates and the full parties view make no
      // sense for a single-branch tenant.
      { href: "/dashboard/affiliates", label: "affiliatesNav", permission: "parties.view", when: (me) => !me.simplified_mode },
      { href: "/dashboard/roles", label: "rolesAndUsers", permission: "roles.manage" },
      {
        href: "/dashboard/settings/parties",
        label: "fullPartiesView",
        permission: "parties.view_all",
        when: (me) => !me.simplified_mode,
      },
      { href: "/dashboard/settings/approval-rules", label: "approvalRulesNav", permission: "approvals.view" },
      { href: "/dashboard/settings/document-numbering", label: "documentNumberingNav", permission: "numbering.view" },
      { href: "/dashboard/settings/attachment-rules", label: "attachmentRulesNav", permission: "attachments.view" },
      // Sprint 6.1 (decision 1): gated by the "manage" permission.
      { href: "/dashboard/settings/fiscal-years", label: "fiscalYearsNav", permission: "accounting.manage_fiscal_periods" },
    ],
  },
];
