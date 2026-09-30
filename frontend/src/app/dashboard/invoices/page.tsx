"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, fieldErrors, generalError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { Money } from "@/components/Money";
import { formatMoney } from "@/lib/money";
import { StatusBadge } from "@/components/StatusBadge";
import { AttachmentPanel } from "@/components/AttachmentPanel";
import { WarningsBanner } from "@/components/WarningsBanner";
import type { CostCenter, CustomerParty, Invoice, LegalEntity, Paginated, Product, TaxCode } from "@/lib/types";

interface LineDraft {
  product: string;
  quantity: string;
  costCenter: string;
  taxCode: string;
}

const EMPTY_LINE: LineDraft = { product: "", quantity: "1", costCenter: "", taxCode: "" };

export default function InvoicesPage() {
  const { t } = useLocale();
  const { me } = useAuth();
  const [customers, setCustomers] = useState<CustomerParty[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [entities, setEntities] = useState<LegalEntity[]>([]);
  const [costCenters, setCostCenters] = useState<CostCenter[]>([]);
  const [taxCodes, setTaxCodes] = useState<TaxCode[]>([]);
  const [editing, setEditing] = useState<Invoice | null>(null);
  const [customerId, setCustomerId] = useState("");
  const [legalEntityId, setLegalEntityId] = useState("");
  // Sprint 6.5.18 (UAT item 5): the LIST's own optional entity filter,
  // separate from `legalEntityId` above (the new-invoice form's field).
  const [listEntityId, setListEntityId] = useState("");
  const [showCostCenters, setShowCostCenters] = useState(false);
  const [showFx, setShowFx] = useState(false);
  const [currency, setCurrency] = useState("");
  const [exchangeRate, setExchangeRate] = useState("");
  const [lines, setLines] = useState<LineDraft[]>([{ ...EMPTY_LINE }]);
  const [refreshToken, setRefreshToken] = useState(0);
  const [showQuickAddCustomer, setShowQuickAddCustomer] = useState(false);
  const [quickCustomerName, setQuickCustomerName] = useState("");
  const [quickAddError, setQuickAddError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});

  // 3.13: legal_entity only needs a visible field once the tenant is out
  // of simplified mode — otherwise the server auto-fills the single branch.
  const needsEntityPicker = !!me && !me.simplified_mode;
  const showCostCenterUI = !!me && me.features.cost_centers;

  const loadFormData = async () => {
    // Sprint 3.5 (3.3 v1.4): the customer picker lists the dedicated
    // /api/parties/customers/ screen's rows, not the generic
    // role-filtered /api/parties/ endpoint (now gated to accounts
    // managers only).
    const [cust, prod, tax] = await Promise.all([
      api.get<Paginated<CustomerParty>>("/parties/customers/"),
      api.get<Paginated<Product>>("/products/"),
      api.get<Paginated<TaxCode>>("/tax-codes/"),
    ]);
    setCustomers(cust.results);
    setProducts(prod.results);
    setTaxCodes(tax.results);

    if (needsEntityPicker) {
      const entityData = await api.get<Paginated<LegalEntity>>("/legal-entities/");
      setEntities(entityData.results.filter((entity) => entity.entity_type !== "holding"));
      // Sprint 6.0.1-B item 6: default to the user's own primary branch
      // instead of forcing an explicit pick every time.
      if (me?.default_legal_entity_id) setLegalEntityId((prev) => prev || me.default_legal_entity_id!);
    }
    if (showCostCenterUI) {
      const ccData = await api.get<Paginated<CostCenter>>("/cost-centers/");
      setCostCenters(ccData.results);
    }
  };

  useEffect(() => {
    loadFormData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needsEntityPicker, showCostCenterUI]);

  const addLine = () => setLines([...lines, { ...EMPTY_LINE }]);
  const updateLine = (index: number, field: keyof LineDraft, value: string) => {
    setLines(
      lines.map((line, i) => {
        if (i !== index) return line;
        const next = { ...line, [field]: value };
        if (field === "product" && !line.taxCode) {
          const product = products.find((p) => p.id === value);
          if (product?.default_tax_code) next.taxCode = product.default_tax_code;
        }
        return next;
      })
    );
  };

  const startEdit = (invoice: Invoice) => {
    setEditing(invoice);
    setCustomerId(invoice.customer);
    setLegalEntityId(invoice.legal_entity);
    setCurrency(invoice.currency);
    setExchangeRate(invoice.exchange_rate);
    setLines(
      invoice.lines.map((line) => ({
        product: line.product,
        quantity: line.quantity,
        costCenter: line.cost_center || "",
        taxCode: line.tax_code,
      }))
    );
    if (invoice.lines.some((line) => line.cost_center)) setShowCostCenters(true);
  };

  const cancelEdit = () => {
    setEditing(null);
    setCustomerId("");
    setLegalEntityId("");
    setCurrency("");
    setExchangeRate("");
    setShowFx(false);
    setLines([{ ...EMPTY_LINE }]);
    setError(null);
    setFieldErr({});
  };

  const onQuickAddCustomer = async (e: React.FormEvent) => {
    e.preventDefault();
    setQuickAddError(null);
    try {
      const created = await api.post<CustomerParty>("/parties/customers/", { name: quickCustomerName });
      setCustomers((prev) => [...prev, created]);
      setCustomerId(created.id);
      setQuickCustomerName("");
      setShowQuickAddCustomer(false);
    } catch (err) {
      setQuickAddError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setFieldErr({});
    const payload = {
      customer: customerId,
      ...(legalEntityId ? { legal_entity: legalEntityId } : {}),
      ...(currency ? { currency } : {}),
      ...(exchangeRate ? { exchange_rate: exchangeRate } : {}),
      lines: lines
        .filter((l) => l.product)
        .map((l) => ({
          product: l.product,
          quantity: l.quantity,
          tax_code: l.taxCode,
          ...(l.costCenter ? { cost_center: l.costCenter } : {}),
        })),
    };
    try {
      let saved: Invoice;
      if (editing) {
        saved = await api.patch<Invoice>(`/invoices/${editing.id}/`, payload);
      } else {
        saved = await api.post<Invoice>("/invoices/", payload);
      }
      setWarnings(saved.warnings || []);
      cancelEdit();
      setRefreshToken((n) => n + 1);
    } catch (err) {
      setFieldErr(fieldErrors((err as { body?: unknown }).body));
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  return (
    <div>
      <h1>{t("invoices")}</h1>
      <WarningsBanner warnings={warnings} />
      <div className="card">
        <h3>{editing ? t("editInvoice") : t("createInvoice")}</h3>
        <form onSubmit={onSubmit}>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <FormField name="customer" label={t("customer")} required error={fieldErr.customer}>
              <div>
                <div style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
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
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => setShowQuickAddCustomer((v) => !v)}
                  >
                    {t("quickAddCustomer")}
                  </button>
                </div>
                {showQuickAddCustomer && (
                  <div style={{ display: "flex", gap: "0.4rem", marginTop: "0.4rem", alignItems: "center" }}>
                    <input
                      value={quickCustomerName}
                      onChange={(e) => setQuickCustomerName(e.target.value)}
                      placeholder={t("name")} // form-ok: حقل ضمن نموذج فرعي سريع بلا FormField خاص به، الخطأ يظهر أدناه عبر quickAddError
                    />
                    <button type="button" className="primary" onClick={onQuickAddCustomer}>
                      {t("save")}
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => {
                        setShowQuickAddCustomer(false);
                        setQuickCustomerName("");
                        setQuickAddError(null);
                      }}
                    >
                      {t("cancel")}
                    </button>
                  </div>
                )}
                {quickAddError && <p className="error-text">{quickAddError}</p>}
              </div>
            </FormField>
          </div>

          {needsEntityPicker && (
            <details style={{ marginTop: "0.75rem" }}>
              <summary style={{ cursor: "pointer" }}>{t("advanced")}</summary>
              <FormField
                name="legal_entity" label={t("legalEntity")} required error={fieldErr.legal_entity}
                style={{ marginTop: "0.75rem", maxWidth: "320px" }}
              >
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
              </FormField>
            </details>
          )}

          {!showFx ? (
            <button type="button" className="secondary" onClick={() => setShowFx(true)} style={{ marginBottom: "0.75rem" }}>
              {t("foldCurrencyFx")}
            </button>
          ) : (
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginBottom: "0.75rem" }}>
              <FormField name="currency" label={t("currency")} error={fieldErr.currency}>
                <input value={currency} onChange={(e) => setCurrency(e.target.value)} maxLength={3} />
              </FormField>
              <FormField name="exchange_rate" label={t("exchangeRateLabel")} error={fieldErr.exchange_rate}>
                <input value={exchangeRate} onChange={(e) => setExchangeRate(e.target.value)} />
              </FormField>
            </div>
          )}

          {lines.map((line, i) => (
            <div key={i} style={{ display: "flex", gap: "0.75rem", alignItems: "end", flexWrap: "wrap" }}>
              <FormField name="product" label={t("product")} required style={{ flex: 1, minWidth: "180px" }}>
                <select value={line.product} onChange={(e) => updateLine(i, "product", e.target.value)} required>
                  <option value="" disabled>
                    —
                  </option>
                  {products.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} ({formatMoney(p.unit_price)})
                    </option>
                  ))}
                </select>
              </FormField>
              <FormField name="quantity" label={t("quantity")} required style={{ width: "120px" }}>
                <input
                  type="number"
                  step="0.01"
                  value={line.quantity}
                  onChange={(e) => updateLine(i, "quantity", e.target.value)}
                  required
                />
              </FormField>
              <FormField name="tax_code" label={t("taxCode")} required style={{ minWidth: "140px" }}>
                <select value={line.taxCode} onChange={(e) => updateLine(i, "taxCode", e.target.value)} required>
                  <option value="" disabled>
                    —
                  </option>
                  {taxCodes.map((tc) => (
                    <option key={tc.id} value={tc.id}>
                      {tc.code} — {tc.rate}%
                    </option>
                  ))}
                </select>
              </FormField>
              {showCostCenterUI && showCostCenters && (
                <FormField name="cost_center" label={t("costCenter")} style={{ minWidth: "160px" }}>
                  <select value={line.costCenter} onChange={(e) => updateLine(i, "costCenter", e.target.value)}>
                    <option value="">{t("none")}</option>
                    {costCenters.map((cc) => (
                      <option key={cc.id} value={cc.id}>
                        {cc.code} — {cc.name}
                      </option>
                    ))}
                  </select>
                </FormField>
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
          <WarningsBanner warnings={error ? [error] : []} variant="error" />
          <button className="primary" type="submit">
            {editing ? t("saveChanges") : t("createInvoice")}
          </button>
          {editing && (
            <button type="button" className="secondary" onClick={cancelEdit} style={{ marginInlineStart: "0.5rem" }}>
              {t("cancel")}
            </button>
          )}
        </form>
      </div>

      {editing && <AttachmentPanel targetType="invoice" targetId={editing.id} />}

      <FormField name="list_entity_filter" label={t("entityFilter")}>
        <select value={listEntityId} onChange={(e) => setListEntityId(e.target.value)}>
          <option value="">{t("allEntities")}</option>
          {entities.map((entity) => (
            <option key={entity.id} value={entity.id}>{entity.code} — {entity.name}</option>
          ))}
        </select>
      </FormField>

      <DataTable<Invoice>
        endpoint="/invoices/"
        extraParams={{ legal_entity: listEntityId }}
        refreshToken={refreshToken}
        hasActiveToggle={false}
        onEdit={startEdit}
        canEdit={(row) => row.status === "draft"}
        columns={[
          { key: "number", label: t("number"), sortable: true },
          { key: "customer_name", label: t("customer") },
          { key: "legal_entity_name", label: t("legalEntity") },
          { key: "status", label: t("status"), render: (row) => <StatusBadge status={row.status} /> },
          { key: "issue_date", label: t("issueDate"), sortable: true },
          { key: "currency", label: t("currency") },
          { key: "subtotal", label: t("subtotal"), render: (row) => <Money amount={row.subtotal} /> },
          { key: "tax_total", label: t("taxTotal"), render: (row) => <Money amount={row.tax_total} /> },
          { key: "total", label: t("total"), sortable: true, render: (row) => <Money amount={row.total} /> },
        ]}
        renderExtraActions={(invoice, reload) => (
          <>
            <Link href={`/dashboard/invoices/${invoice.id}`} className="secondary" style={{ marginInlineEnd: "0.4rem" }}>
              {t("details")}
            </Link>
            {invoice.status === "draft" && (
              <button
                className="secondary"
                onClick={async () => {
                  const issued = await api.post<Invoice>(`/invoices/${invoice.id}/issue/`);
                  setWarnings(issued.warnings || []);
                  reload();
                }}
              >
                {t("issue")}
              </button>
            )}
            {invoice.status === "pending_approval" && (
              <>
                <button
                  className="secondary"
                  onClick={async () => {
                    await api.post(`/invoices/${invoice.id}/approve/`);
                    reload();
                  }}
                >
                  {t("approve")}
                </button>
                <button
                  className="secondary"
                  style={{ marginInlineStart: "0.4rem" }}
                  onClick={async () => {
                    const reason = window.prompt(t("rejectReason")) || "";
                    if (!reason) return;
                    await api.post(`/invoices/${invoice.id}/reject/`, { reason });
                    reload();
                  }}
                >
                  {t("reject")}
                </button>
              </>
            )}
            {invoice.status === "issued" && (
              <button
                className="secondary"
                onClick={async () => {
                  if (!window.confirm(t("confirmVoid"))) return;
                  let reason = "";
                  if (invoice.delivered_at) {
                    reason = window.prompt(t("postDeliveryVoidReason")) || "";
                    if (!reason) return;
                  }
                  try {
                    await api.post(`/invoices/${invoice.id}/void/`, { reason });
                    reload();
                  } catch (err) {
                    window.alert(generalError((err as { body?: unknown }).body, t("couldNotSave")));
                  }
                }}
              >
                {t("void")}
              </button>
            )}
            {invoice.is_post_delivery_void && (
              <span
                style={{
                  marginInlineStart: "0.4rem", padding: "0.1rem 0.5rem", borderRadius: "var(--radius-pill)",
                  fontSize: "0.75rem", color: "var(--status-void)", background: "var(--status-void-bg)",
                }}
              >
                {t("postDeliveryVoidBadge")}
              </span>
            )}
          </>
        )}
      />
    </div>
  );
}
