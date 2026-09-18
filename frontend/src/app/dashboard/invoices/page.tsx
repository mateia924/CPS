"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import type { Customer, Invoice, Paginated, Product } from "@/lib/types";

interface LineDraft {
  product: string;
  quantity: string;
}

export default function InvoicesPage() {
  const { t } = useLocale();
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [customerId, setCustomerId] = useState("");
  const [lines, setLines] = useState<LineDraft[]>([{ product: "", quantity: "1" }]);

  const load = async () => {
    const [inv, cust, prod] = await Promise.all([
      api.get<Paginated<Invoice>>("/invoices/"),
      api.get<Paginated<Customer>>("/customers/"),
      api.get<Paginated<Product>>("/products/"),
    ]);
    setInvoices(inv.results);
    setCustomers(cust.results);
    setProducts(prod.results);
  };

  useEffect(() => {
    load();
  }, []);

  const addLine = () => setLines([...lines, { product: "", quantity: "1" }]);
  const updateLine = (index: number, field: keyof LineDraft, value: string) => {
    setLines(lines.map((line, i) => (i === index ? { ...line, [field]: value } : line)));
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await api.post("/invoices/", {
      customer: customerId,
      lines: lines
        .filter((l) => l.product)
        .map((l) => ({ product: l.product, quantity: l.quantity })),
    });
    setCustomerId("");
    setLines([{ product: "", quantity: "1" }]);
    load();
  };

  const issueInvoice = async (id: string) => {
    await api.post(`/invoices/${id}/issue/`, {});
    load();
  };

  return (
    <div>
      <h1>{t("invoices")}</h1>
      <div className="card">
        <h3>{t("createInvoice")}</h3>
        <form onSubmit={onSubmit}>
          <div className="form-field">
            <label>{t("customer")}</label>
            <select value={customerId} onChange={(e) => setCustomerId(e.target.value)} required>
              <option value="" disabled>
                —
              </option>
              {customers.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>

          {lines.map((line, i) => (
            <div key={i} style={{ display: "flex", gap: "0.75rem", alignItems: "end" }}>
              <div className="form-field" style={{ flex: 1 }}>
                <label>{t("product")}</label>
                <select value={line.product} onChange={(e) => updateLine(i, "product", e.target.value)} required>
                  <option value="" disabled>
                    —
                  </option>
                  {products.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} ({p.unit_price})
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-field" style={{ width: "120px" }}>
                <label>{t("quantity")}</label>
                <input
                  type="number"
                  step="0.01"
                  value={line.quantity}
                  onChange={(e) => updateLine(i, "quantity", e.target.value)}
                  required
                />
              </div>
            </div>
          ))}

          <button type="button" className="secondary" onClick={addLine} style={{ marginBottom: "1rem" }}>
            {t("addLine")}
          </button>
          <br />
          <button className="primary" type="submit">
            {t("createInvoice")}
          </button>
        </form>
      </div>

      <table>
        <thead>
          <tr>
            <th>{t("number")}</th>
            <th>{t("customer")}</th>
            <th>{t("status")}</th>
            <th>{t("issueDate")}</th>
            <th>{t("subtotal")}</th>
            <th>{t("taxTotal")}</th>
            <th>{t("total")}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {invoices.map((inv) => (
            <tr key={inv.id}>
              <td>{inv.number}</td>
              <td>{inv.customer_name}</td>
              <td>{t(inv.status)}</td>
              <td>{inv.issue_date}</td>
              <td>{inv.subtotal}</td>
              <td>{inv.tax_total}</td>
              <td>{inv.total}</td>
              <td>
                {inv.status === "draft" && (
                  <button className="secondary" onClick={() => issueInvoice(inv.id)}>
                    {t("issue")}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
