export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface Customer {
  id: string;
  name: string;
  email: string;
  phone: string;
  tax_number: string;
  address: string;
  is_active: boolean;
}

export interface Product {
  id: string;
  sku: string;
  name: string;
  unit_price: string;
  tax_rate: string;
  default_tax_code: string | null;
  is_active: boolean;
}

export interface InvoiceLine {
  id: string;
  product: string;
  cost_center: string | null;
  tax_code: string;
  tax_code_display: string;
  description: string;
  quantity: string;
  unit_price: string;
  tax_rate: string;
  line_subtotal: string;
  line_tax: string;
  line_total: string;
}

export type DocumentStatus =
  | "draft"
  | "pending_approval"
  | "approved"
  | "posted"
  | "reversed"
  | "issued"
  | "paid"
  | "cancelled";

export type PaymentStatus = "unpaid" | "partial" | "paid";

export interface Invoice {
  id: string;
  number: string;
  status: DocumentStatus;
  created_by: string | null;
  issue_date: string;
  due_date: string | null;
  customer: string;
  customer_name: string;
  customer_party_type: PartyType;
  legal_entity: string;
  legal_entity_name: string;
  currency: string;
  exchange_rate: string;
  subtotal: string;
  tax_total: string;
  total: string;
  base_total: string;
  paid_fc: string;
  balance_fc: string;
  payment_status: PaymentStatus;
  delivered_at: string | null;
  lines: InvoiceLine[];
}

export type LegalEntityType = "holding" | "company" | "branch";

export interface CompanyProfile {
  commercial_registration: string;
  building_number: string;
  street: string;
  district: string;
  city: string;
  postal_code: string;
  short_address: string;
  phone: string;
  email: string;
}

export interface LegalEntity extends CompanyProfile {
  id: string;
  parent: string | null;
  code: string;
  name: string;
  entity_type: LegalEntityType;
  country_code: string;
  tax_number: string;
  base_currency: string;
  effective_profile: CompanyProfile;
  is_active: boolean;
}

export interface LegalEntityTreeNode {
  id: string;
  code: string;
  name: string;
  entity_type: LegalEntityType;
  is_active: boolean;
  children: LegalEntityTreeNode[];
}

export type CostCenterType =
  | "department"
  | "vehicle"
  | "warehouse"
  | "employee"
  | "project"
  | "general";

export interface CostCenter {
  id: string;
  parent: string | null;
  code: string;
  name: string;
  center_type: CostCenterType;
  is_active: boolean;
}

export interface CostCenterTreeNode {
  id: string;
  code: string;
  name: string;
  center_type: CostCenterType;
  is_active: boolean;
  children: CostCenterTreeNode[];
}

export interface Role {
  id: string;
  name: string;
  is_system: boolean;
  permission_codes: string[];
}

export interface Permission {
  code: string;
  description: string;
}

export interface TenantUser {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  is_active: boolean;
  role_ids: string[];
  role_names: string[];
  legal_entity_ids: string[];
}

export interface MeFeatures {
  organization: boolean;
  cost_centers: boolean;
  inventory: boolean;
  purchasing: boolean;
  hr: boolean;
  treasury: boolean;
  assets: boolean;
}

export interface MeResponse {
  tenant: { id: string; name: string; subdomain: string };
  user: { id: string; email: string; first_name: string; last_name: string };
  roles: string[];
  permissions: string[];
  legal_entity_ids: string[];
  features: MeFeatures;
  simplified_mode: boolean;
}

// --- Platform (sprint 2, docs/SYSTEM_ANALYSIS.md 3.14) ---

export type PlatformRole = "super_admin" | "support" | "billing";

export interface PlatformUser {
  id: string;
  email: string;
  full_name: string;
  role: PlatformRole;
}

export type TenantStatus = "trial" | "active" | "past_due" | "suspended" | "archived";

export interface Plan {
  id: number;
  code: string;
  name: string;
  is_active: boolean;
  max_users: number | null;
  max_branches: number | null;
  max_invoices_per_month: number | null;
  storage_mb: number | null;
  feature_organization: boolean;
  feature_cost_centers: boolean;
  feature_inventory: boolean;
  feature_purchasing: boolean;
  feature_hr: boolean;
}

export interface PlatformTenant {
  id: string;
  name: string;
  subdomain: string;
  plan: number;
  plan_code: string;
  status: TenantStatus;
  trial_ends_at: string | null;
  user_count: number;
  invoice_count: number;
  last_activity: string | null;
  created_at: string;
}

export interface AuditLogEntry {
  id: string;
  actor_type: "platform" | "tenant_user";
  actor_id: string | null;
  action: string;
  target_type: string;
  target_id: string | null;
  tenant_id: string | null;
  before: unknown;
  after: unknown;
  ip_address: string | null;
  user_agent: string;
  created_at: string;
}

// --- Master data (sprint 3, docs/SYSTEM_ANALYSIS.md 3.3) ---

export type PartyRoleType = "customer" | "supplier" | "employee" | "affiliate" | "bank";

export interface PartyRole {
  id: string;
  role: PartyRoleType;
  is_active: boolean;
  details: Record<string, unknown>;
  legal_entity: string | null;
  created_at: string;
}

export type PartyType = "individual" | "organization";

export interface Party {
  id: string;
  code: string;
  name: string;
  name_en: string;
  party_type: PartyType;
  tax_number: string;
  national_id_or_cr: string;
  phone: string;
  email: string;
  address: Record<string, unknown>;
  country_code: string;
  default_currency: string;
  notes: string;
  is_active: boolean;
  roles: PartyRole[];
  created_at: string;
}

export interface Bank {
  id: string;
  legal_entity: string;
  name: string;
  bank_name: string;
  account_number: string;
  iban: string;
  swift: string;
  currency: string;
  is_active: boolean;
  created_at: string;
}

export interface CashBox {
  id: string;
  legal_entity: string;
  name: string;
  currency: string;
  custodian: string | null;
  max_balance: string | null;
  is_active: boolean;
  created_at: string;
}

export interface Custody {
  id: string;
  legal_entity: string;
  employee: string;
  name: string;
  currency: string;
  limit_amount: string | null;
  is_active: boolean;
  created_at: string;
}

// --- Sprint 5.4 (block 5.4): shared by treasury movements + party
// statements (and 5.7's general ledger, same shape).
export interface LedgerLine {
  date: string;
  entry_id: string;
  entry_number: string;
  description: string;
  debit: string;
  credit: string;
  debit_fc: string;
  credit_fc: string;
  currency: string;
  running_balance: string;
  running_balance_fc: string;
  source_type: string;
  source_id: string | null;
}

export interface LedgerStatement {
  opening_balance: string;
  opening_balance_fc: string;
  lines: LedgerLine[];
  closing_balance: string;
  closing_balance_fc: string;
}

export interface OpenInvoiceSummary {
  id: string;
  number: string;
  issue_date: string;
  due_date: string | null;
  currency: string;
  total: string;
  balance_fc: string;
}

export interface PartyStatement extends LedgerStatement {
  open_invoices: OpenInvoiceSummary[];
}

export type AssetCategory = "vehicle" | "equipment" | "building" | "furniture" | "it" | "other";
export type AssetStatus = "active" | "disposed" | "under_maintenance";

export interface Asset {
  id: string;
  legal_entity: string;
  code: string;
  name: string;
  category: AssetCategory;
  purchase_date: string;
  purchase_cost: string;
  currency: string;
  useful_life_months: number | null;
  salvage_value: string;
  depreciation_method: "straight_line";
  custodian: string | null;
  cost_center: string | null;
  status: AssetStatus;
  is_active: boolean;
  created_at: string;
}

// --- Sprint 3.5 (docs/SYSTEM_ANALYSIS.md 3.3 v1.4): dedicated,
// role-fixed master-data screens — no "role" field, ever, on any of
// these. Each is still a Party/PartyRole under the hood (`roles` comes
// back for the duplicate-confirm dialog only, never as an editable
// field on these screens).

export interface CustomerParty {
  id: string;
  code: string;
  name: string;
  name_en: string;
  party_type: PartyType;
  tax_number: string;
  national_id_or_cr: string;
  phone: string;
  email: string;
  country_code: string;
  default_currency: string;
  notes: string;
  is_active: boolean;
  roles: PartyRole[];
  created_at: string;
  credit_limit: string | null;
  payment_terms_days: number | null;
  sales_rep: string | null;
}

export interface SupplierParty {
  id: string;
  code: string;
  name: string;
  name_en: string;
  party_type: PartyType;
  tax_number: string;
  national_id_or_cr: string;
  phone: string;
  email: string;
  country_code: string;
  default_currency: string;
  notes: string;
  is_active: boolean;
  roles: PartyRole[];
  created_at: string;
  payment_terms_days: number | null;
  iban: string | null;
}

export interface EmployeeParty {
  id: string;
  code: string;
  name: string;
  name_en: string;
  party_type: PartyType;
  tax_number: string;
  national_id_or_cr: string;
  phone: string;
  email: string;
  country_code: string;
  default_currency: string;
  notes: string;
  is_active: boolean;
  roles: PartyRole[];
  created_at: string;
  hire_date: string | null;
  job_title: string | null;
  direct_manager: string | null;
  salary_currency: string | null;
  branch: string | null;
  create_linked_cost_center?: boolean;
}

export interface AffiliateParty {
  id: string;
  code: string;
  name: string;
  name_en: string;
  party_type: PartyType;
  tax_number: string;
  national_id_or_cr: string;
  phone: string;
  email: string;
  country_code: string;
  default_currency: string;
  notes: string;
  is_active: boolean;
  roles: PartyRole[];
  created_at: string;
  legal_entity: string | null;
}

export interface DuplicateCheckResponse {
  party: Party | null;
}

// --- Sprint 4 (docs/SYSTEM_ANALYSIS.md 3.4/3.11/3.15/3.16/3.18) ---

export type AccountType = "asset" | "liability" | "equity" | "revenue" | "expense";
export type NormalBalance = "debit" | "credit";

export interface Account {
  id: string;
  parent: string | null;
  level: number;
  code: string;
  name: string;
  type: AccountType;
  normal_balance: NormalBalance;
  allow_posting: boolean;
  is_intercompany: boolean;
  system_key: string;
  is_system: boolean;
  party: string | null;
  is_leaf: boolean;
  is_active: boolean;
  created_at: string;
}

export interface AccountTreeNode {
  id: string;
  code: string;
  name: string;
  type: AccountType;
  normal_balance: NormalBalance;
  is_system: boolean;
  system_key: string;
  is_active: boolean;
  balance: string;
  children: AccountTreeNode[];
}

export interface JournalLine {
  id: string;
  account: string;
  account_code: string;
  account_name: string;
  account_system_key: string;
  cost_center: string | null;
  party: string | null;
  description: string;
  debit: string;
  credit: string;
  debit_fc: string;
  credit_fc: string;
}

export interface JournalEntry {
  id: string;
  legal_entity: string;
  legal_entity_name: string;
  date: string;
  memo: string;
  reference: string;
  number: string;
  status: DocumentStatus;
  created_by: string | null;
  reverses: string | null;
  source_type: string;
  source_id: string | null;
  currency: string;
  exchange_rate: string;
  created_at: string;
  lines: JournalLine[];
}

export interface ManualJournalLineInput {
  account: string;
  cost_center?: string;
  description?: string;
  debit_fc: string;
  credit_fc: string;
}

export type TaxCodeKind = "standard" | "zero_rated" | "exempt" | "out_of_scope" | "reverse_charge";
export type TaxCodeDirection = "output" | "input" | "both";
export type TaxCodeDeductible = "full" | "none";

export interface TaxCode {
  id: string;
  code: string;
  name: string;
  rate: string;
  kind: TaxCodeKind;
  direction: TaxCodeDirection;
  deductible: TaxCodeDeductible;
  account: string | null;
  country_code: string;
  effective_from: string;
  is_active: boolean;
  created_at: string;
}

export type TaxPeriodType = "monthly" | "quarterly";
export type TaxPeriodStatus = "open" | "filed" | "paid";

export interface TaxPeriod {
  id: string;
  legal_entity: string;
  period_type: TaxPeriodType;
  start: string;
  end: string;
  status: TaxPeriodStatus;
  filed_at: string | null;
  reference: string;
  created_at: string;
}

export type ApprovalDocType =
  | "journal_entry" | "invoice"
  | "voucher_receipt" | "voucher_payment" | "voucher_settlement";

export interface ApprovalRule {
  id: string;
  doc_type: ApprovalDocType;
  min_amount: string;
  required_role: string;
  is_active: boolean;
  created_at: string;
}

export interface ExchangeRate {
  id: string;
  from_currency: string;
  to_currency: string;
  date: string;
  rate: string;
  source: string;
  created_by: string | null;
  created_at: string;
}

export interface DocumentNumberingSetting {
  id: string;
  doc_type: string;
  prefix: string;
  reset_yearly: boolean;
  include_entity_code: boolean | null;
}

// --- Sprint 5.1 (docs/SYSTEM_ANALYSIS.md 3.17) ---

export type AttachmentTargetType =
  | "party" | "bank" | "cash_box" | "custody" | "asset"
  | "invoice" | "journal_entry" | "voucher"
  | "account" | "tax_code" | "exchange_rate" | "legal_entity";

export type AttachmentCategory =
  | "fatura_original" | "receipt" | "contract" | "bank_letter"
  | "id_document" | "approval_minutes" | "other";

export type AttachmentScanStatus = "pending" | "clean" | "infected" | "error" | "skipped";
export type AttachmentIntegrityStatus = "unchecked" | "ok" | "mismatch";

export interface Attachment {
  id: string;
  target_type: AttachmentTargetType;
  object_id: string;
  category: AttachmentCategory;
  description: string;
  original_name: string;
  mime_type: string;
  size: number;
  sha256: string;
  uploaded_by_email: string;
  uploaded_at: string;
  status: "active" | "voided";
  void_reason: string;
  voided_by_email: string;
  voided_at: string | null;
  version: number;
  supersedes: string | null;
  scan_status: AttachmentScanStatus;
  scanned_at: string | null;
  integrity_status: AttachmentIntegrityStatus;
}

export interface PendingApproval {
  doc_type: ApprovalDocType;
  id: string;
  number: string;
  date: string;
  description: string;
  amount_base: string;
  created_by: string | null;
}

// --- Sprint 5.3/5.4 (docs/SYSTEM_ANALYSIS.md 3.8): سندات القبض/الصرف/التسوية ---

export type VoucherType = "receipt" | "payment" | "settlement";
export type SettlementKind = "internal_transfer";
export type TreasuryKind = "bank" | "cash_box" | "custody";
export type VoucherPaymentMethod = "cash" | "bank_transfer" | "cheque" | "card" | "other";
export type VoucherLineType = "invoice" | "on_account" | "account";

export interface VoucherLine {
  id: string;
  line_no: number;
  line_type: VoucherLineType;
  invoice: string | null;
  allocated_invoice_fc: string | null;
  account: string | null;
  tax_code: string | null;
  amount_includes_tax: boolean;
  tax_amount_fc: string;
  ext_supplier_name: string;
  ext_supplier_tax_number: string;
  ext_invoice_ref: string;
  cost_center: string | null;
  description: string;
  amount_fc: string;
  amount_base: string;
  tax_amount_base: string;
}

export interface Voucher {
  id: string;
  voucher_type: VoucherType;
  settlement_kind: SettlementKind | null;
  number: string;
  date: string;
  currency: string;
  exchange_rate: string;
  exchange_rate_overridden: boolean;
  treasury_kind: TreasuryKind;
  bank: string | null;
  cash_box: string | null;
  custody: string | null;
  treasury_name: string;
  counter_treasury_kind: TreasuryKind | null;
  counter_bank: string | null;
  counter_cash_box: string | null;
  counter_custody: string | null;
  counter_amount_fc: string | null;
  counter_treasury_name: string;
  legal_entity: string;
  legal_entity_name: string;
  party: string | null;
  party_name: string;
  party_role: PartyRoleType | null;
  payee_name: string;
  payment_method: VoucherPaymentMethod;
  reference: string;
  description: string;
  status: DocumentStatus;
  total_fc: string;
  total_base: string;
  journal_entry_id: string | null;
  created_by: string | null;
  posted_at: string | null;
  reversal_of: string | null;
  lines: VoucherLine[];
  created_at: string;
}
