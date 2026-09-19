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
  is_active: boolean;
}

export interface InvoiceLine {
  id: string;
  product: string;
  cost_center: string | null;
  description: string;
  quantity: string;
  unit_price: string;
  tax_rate: string;
  line_subtotal: string;
  line_tax: string;
  line_total: string;
}

export interface Invoice {
  id: string;
  number: string;
  status: "draft" | "issued" | "paid" | "cancelled";
  issue_date: string;
  customer: string;
  customer_name: string;
  legal_entity: string;
  legal_entity_name: string;
  subtotal: string;
  tax_total: string;
  total: string;
  lines: InvoiceLine[];
}

export type LegalEntityType = "holding" | "company" | "branch";

export interface LegalEntity {
  id: string;
  parent: string | null;
  code: string;
  name: string;
  entity_type: LegalEntityType;
  country_code: string;
  tax_number: string;
  base_currency: string;
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
  is_active: boolean;
  created_at: string;
}

export interface Custody {
  id: string;
  legal_entity: string;
  employee: string;
  name: string;
  currency: string;
  is_active: boolean;
  created_at: string;
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
