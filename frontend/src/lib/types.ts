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
