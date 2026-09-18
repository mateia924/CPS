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
  subtotal: string;
  tax_total: string;
  total: string;
  lines: InvoiceLine[];
}
