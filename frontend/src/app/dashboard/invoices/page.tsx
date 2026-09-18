"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import type { Customer, CostCenter, Invoice, LegalEntity, Paginated, Product } from "@/lib/types";

interface LineDraft {
  product: string;
  quantity: string;
  costCenter: string;
}

export default function InvoicesPage() {
  const { t } = useLocale();
  const { me } = useAuth();
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [entities, setEntities] = useState<LegalEntity[]>([]);
  const [costCenters, setCostCenters] = useState<CostCenter[]>([]);
  const [customerId, setCustomerId] = useState("");
  const [legalEntityId, setLegalEntityId] = useState("");
  const [showCostCenters, setShowCostCenters] = useState(false);
  const [lines, setLines] = useState<LineDraft[]>([{ product: "", quantity: "1", costCenter: "" }]);

  // 3.13: legal_entity only needs a visible field once the tenant is out
  // of simplified mode — otherwise the server auto-fills the single branch.
  const needsEntityPicker = !!me && !me.simplified_mode;
  const showCostCenterUI = !!me && me.features.cost_centers;

  const load = async () => {
    const requests: [
      Promise<Paginated<Invoice>>,
      Promise<Paginated<Customer>>,
      Promise<Paginated<Product>>,
    ] = [
      api.get<Paginated<Invoice>>("/invoices/"),
      api.get<Paginated<Customer>>("/customers/"),
      api.get<Paginated<Product>>("/products/"),
    ];
    const [inv, cust, prod] = await Promise.all(requests);
    setInvoices(inv.results);
    setCustomers(cust.results);
    setProducts(prod.results);

    if (needsEntityPicker) {
      const entityData = await api.get<Paginated<LegalEntity>>("/legal-entities/");
      setEntities(entityData.results.filter((entity) => entity.entity_type !== "holding"));
    }
    if (showCostCenterUI) {
      const ccData = await api.get<Paginated<CostCenter>>("/cost-centers/");
      setCostCenters(ccData.results);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needsEntityPicker, showCostCenterUI]);

  const addLine = () => setLines([...lines, { product: "", quantity: "1", costCenter: "" }]);
  const updateLine = (index: number, field: keyof LineDraft, value: string) => {
    setLines(lines.map((line, i) => (i === index ? { ...line, [field]: value } : line)));
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await api.post("/invoices/", {
      customer: customerId,
      ...(legalEntityId ? { legal_entity: legalEntityId } : {}),
      lines: lines
        .filter((l) => l.product)
        .map((l) => ({
          product: l.product,
          quantity: l.quantity,
          ...(l.costCenter ? { cost_center: l.costCenter } : {}),
        })),
    });
    setCustomerId("");
    setLegalEntityId("");
    setLines([{ product: "", quantity: "1", costCenter: "" }]);
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
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
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

            {needsEntityPicker && (
              <div className="form-field">
                <label>{t("legalEntity")}</label>
                <select value={legalEntityId} onChange={(e) => setLegalEntityId(e.target.value)} required>
                  <option value="" disabled>
                    —
                  </option>
                  {entities.map((entity) => (
                    <option key={entity.id} value={entity.id}>
                      {entity.code} — {entity.name}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          {lines.map((line, i) => (
            <div key={i} style={{ display: "flex", gap: "0.75rem", alignItems: "end", flexWrap: "wrap" }}>
              <div className="form-field" style={{ flex: 1, minWidth: "180px" }}>
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
              {showCostCenterUI && showCostCenters && (
                <div className="form-field" style={{ minWidth: "160px" }}>
                  <label>{t("costCenter")}</label>
                  <select value={line.costCenter} onChange={(e) => updateLine(i, "costCenter", e.target.value)}>
                    <option value="">{t("none")}</option>
                    {costCenters.map((cc) => (
                      <option key={cc.id} value={cc.id}>
                        {cc.code} — {cc.name}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>
          ))}

          {showCostCenterUI && !showCostCenters && (
            <button
              type="button"
              className="secondary"
              onClick={() => setShowCostCenters(true)}
              style={{ marginBottom: "0.75rem" }}
            >
              {t("distributeCostCenters")}
            </button>
          )}
          <br />
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
            <th>{t("legalEntity")}</th>
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
              <td>{inv.legal_entity_name}</td>
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
