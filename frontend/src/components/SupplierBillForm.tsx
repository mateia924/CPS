"use client";

import { useEffect, useState } from "react";
import { api, fieldErrors, generalError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import { FormField } from "@/components/FormField";
import { WarningsBanner } from "@/components/WarningsBanner";
import type { SupplierBill, SupplierBillFormOptions, SupplierBillLineType } from "@/lib/types";

interface LineDraft {
  lineType: SupplierBillLineType;
  description: string;
  account: string;
  costCenter: string;
  qty: string;
  unitPrice: string;
  taxCode: string;
  vatDeductible: boolean;
  whtCode: string;
  assetName: string;
  assetCategory: string;
}

const LINE_TYPES: { value: SupplierBillLineType; label: string }[] = [
  { value: "service", label: "billLineService" },
  { value: "expense", label: "billLineExpense" },
  { value: "asset", label: "billLineAsset" },
];

function emptyLine(lineType: SupplierBillLineType = "expense", account = "", taxCode = ""): LineDraft {
  return {
    lineType, description: "", account, costCenter: "", qty: "1", unitPrice: "", taxCode, vatDeductible: true,
    whtCode: "", assetName: "", assetCategory: "",
  };
}

/** Sprint 8.1 (D12): header + lines of a supplier bill, new or a DRAFT
 * being edited (full replace, like the stock documents). The line type
 * decides the fields: service — description + account; expense — account
 * + cost center; asset — asset name + category (the account is always
 * FIXED_ASSETS, the server sets it). VAT per line with a «قابلة للخصم»
 * switch, withholding per line. Every amount and total is the server's.
 * Pick lists come from /purchasing/bills/form-options/, behind the bill's
 * own permission — a Purchasing user holds none of the accounting /
 * parties / organization permissions those lists usually need. */
export function SupplierBillForm({
  bill,
  onSaved,
  onCancel,
}: {
  bill?: SupplierBill;
  onSaved: (bill: SupplierBill) => void;
  onCancel?: () => void;
}) {
  const { t } = useLocale();
  const { me } = useAuth();
  const [options, setOptions] = useState<SupplierBillFormOptions | null>(null);
  const [supplierSearch, setSupplierSearch] = useState("");
  const [legalEntityId, setLegalEntityId] = useState(bill?.legal_entity ?? "");
  const [supplierId, setSupplierId] = useState(bill?.supplier ?? "");
  const [billNumber, setBillNumber] = useState(bill?.bill_number ?? "");
  const [date, setDate] = useState(bill?.date ?? new Date().toISOString().slice(0, 10));
  const [dueDate, setDueDate] = useState(bill?.due_date ?? "");
  const [currency, setCurrency] = useState(bill?.currency ?? "");
  const [exchangeRate, setExchangeRate] = useState(bill && bill.exchange_rate !== "1.00000000" ? bill.exchange_rate : "");
  const [reference, setReference] = useState(bill?.reference ?? "");
  const [notes, setNotes] = useState(bill?.notes ?? "");
  const [lines, setLines] = useState<LineDraft[]>(
    bill
      ? bill.lines.map((l) => ({
          lineType: l.line_type, description: l.description, account: l.account ?? "", costCenter: l.cost_center ?? "",
          qty: l.qty, unitPrice: l.unit_price, taxCode: l.tax_code, vatDeductible: l.vat_deductible,
          whtCode: l.wht_code ?? "", assetName: l.asset_name, assetCategory: l.asset_category,
        }))
      : [],
  );
  const [error, setError] = useState<string | null>(null);
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get<SupplierBillFormOptions>("/purchasing/bills/form-options/").then((data) => {
      setOptions(data);
      if (!bill) {
        if (data.legal_entities.length === 1) setLegalEntityId((prev) => prev || data.legal_entities[0].id);
        else if (me?.default_legal_entity_id) setLegalEntityId((prev) => prev || me.default_legal_entity_id!);
        const standard = data.tax_codes.find((c) => c.code === "S");
        setLines([emptyLine("expense", "", standard?.id ?? "")]);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!options) return null;

  const entity = options.legal_entities.find((e) => e.id === legalEntityId);
  const baseCurrency = entity?.base_currency ?? "";
  const foreign = !!currency && !!baseCurrency && currency.toUpperCase() !== baseCurrency;
  const needle = supplierSearch.trim().toLowerCase();
  const suppliers = needle
    ? options.suppliers.filter((s) => s.name.toLowerCase().includes(needle) || s.code.toLowerCase().includes(needle))
    : options.suppliers;
  const selectedSupplier = options.suppliers.find((s) => s.id === supplierId);

  const updateLine = (index: number, patch: Partial<LineDraft>) => {
    setLines((prev) => prev.map((line, i) => (i === index ? { ...line, ...patch } : line)));
  };

  const pickSupplier = (id: string) => {
    setSupplierId(id);
    const supplier = options.suppliers.find((s) => s.id === id);
    // A supplier's default expense account (D2) fills lines that have none.
    if (supplier?.default_expense_account) {
      setLines((prev) =>
        prev.map((l) => (l.lineType !== "asset" && !l.account ? { ...l, account: supplier.default_expense_account! } : l)),
      );
    }
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setFieldErr({});
    const payload = {
      legal_entity: legalEntityId,
      supplier: supplierId,
      bill_number: billNumber,
      date,
      due_date: dueDate || null,
      ...(currency ? { currency: currency.toUpperCase() } : {}),
      ...(foreign && exchangeRate ? { exchange_rate: exchangeRate } : {}),
      reference,
      notes,
      lines: lines
        .filter((l) => l.unitPrice)
        .map((l) => ({
          line_type: l.lineType,
          description: l.description,
          ...(l.lineType !== "asset" && l.account ? { account: l.account } : {}),
          ...(l.costCenter ? { cost_center: l.costCenter } : {}),
          qty: l.qty || "1",
          unit_price: l.unitPrice,
          tax_code: l.taxCode,
          vat_deductible: l.vatDeductible,
          ...(l.whtCode ? { wht_code: l.whtCode } : {}),
          ...(l.lineType === "asset" ? { asset_name: l.assetName, asset_category: l.assetCategory } : {}),
        })),
    };
    setSaving(true);
    try {
      const saved = bill
        ? await api.patch<SupplierBill>(`/purchasing/bills/${bill.id}/`, payload)
        : await api.post<SupplierBill>("/purchasing/bills/", payload);
      onSaved(saved);
    } catch (err) {
      const body = (err as { body?: unknown }).body;
      setFieldErr(fieldErrors(body));
      setError(generalError(body, t("couldNotSave"), (err as { status?: number }).status));
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={onSubmit} data-testid="supplier-bill-form">
      <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
        <FormField name="legal_entity" label={t("legalEntity")} required error={fieldErr.legal_entity} style={{ minWidth: "220px" }}>
          <select value={legalEntityId} onChange={(e) => setLegalEntityId(e.target.value)} required>
            <option value="" disabled>—</option>
            {options.legal_entities.map((e) => (
              <option key={e.id} value={e.id}>{e.code} — {e.name}</option>
            ))}
          </select>
        </FormField>
        <FormField name="supplier_search" label={t("billSupplierSearch")}>
          <input value={supplierSearch} onChange={(e) => setSupplierSearch(e.target.value)} />
        </FormField>
        <FormField name="supplier" label={t("billSupplier")} required error={fieldErr.supplier} style={{ minWidth: "240px" }}>
          <select value={supplierId} onChange={(e) => pickSupplier(e.target.value)} required>
            <option value="" disabled>—</option>
            {selectedSupplier && !suppliers.includes(selectedSupplier) && (
              <option value={selectedSupplier.id}>{selectedSupplier.code} — {selectedSupplier.name}</option>
            )}
            {suppliers.map((s) => (
              <option key={s.id} value={s.id}>{s.code} — {s.name}</option>
            ))}
          </select>
        </FormField>
        <FormField name="bill_number" label={t("supplierInvoiceNumber")} required error={fieldErr.bill_number}>
          <input value={billNumber} onChange={(e) => setBillNumber(e.target.value)} required />
        </FormField>
        <FormField name="date" label={t("billDate")} required error={fieldErr.date}>
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
        </FormField>
        <FormField name="due_date" label={t("dueDate")} error={fieldErr.due_date}>
          <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
        </FormField>
        <FormField name="currency" label={t("currency")} error={fieldErr.currency} hint={baseCurrency}>
          <input value={currency} placeholder={baseCurrency} maxLength={3} onChange={(e) => setCurrency(e.target.value)} style={{ width: "6rem" }} />
        </FormField>
        {foreign && (
          <FormField name="exchange_rate" label={t("billExchangeRate")} error={fieldErr.exchange_rate}>
            <input type="number" step="0.00000001" min="0" value={exchangeRate} onChange={(e) => setExchangeRate(e.target.value)} />
          </FormField>
        )}
        <FormField name="reference" label={t("reference")} hint={t("billReferenceHint")} error={fieldErr.reference}>
          <input value={reference} onChange={(e) => setReference(e.target.value)} />
        </FormField>
      </div>

      <h3>{t("billLines")}</h3>
      <FormField name="lines" error={fieldErr.lines}>
        <div>
          {lines.map((line, index) => (
            <div key={index} className="card" data-testid={`bill-line-${index + 1}`} style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "flex-end" }}>
              <FormField name={`line_type_${index}`} label={t("billLineType")}>
                <select value={line.lineType} onChange={(e) => updateLine(index, { lineType: e.target.value as SupplierBillLineType })}>
                  {LINE_TYPES.map((lt) => (
                    <option key={lt.value} value={lt.value}>{t(lt.label)}</option>
                  ))}
                </select>
              </FormField>
              {line.lineType === "asset" ? (
                <>
                  <FormField name={`asset_name_${index}`} label={t("billAssetName")}>
                    <input value={line.assetName} onChange={(e) => updateLine(index, { assetName: e.target.value })} />
                  </FormField>
                  <FormField name={`asset_category_${index}`} label={t("billAssetCategory")}>
                    <select value={line.assetCategory} onChange={(e) => updateLine(index, { assetCategory: e.target.value })}>
                      <option value="">—</option>
                      {options.asset_categories.map((c) => (
                        <option key={c.value} value={c.value}>{t(c.value)}</option>
                      ))}
                    </select>
                  </FormField>
                </>
              ) : (
                <>
                  <FormField name={`description_${index}`} label={t("description")}>
                    <input value={line.description} onChange={(e) => updateLine(index, { description: e.target.value })} />
                  </FormField>
                  <FormField name={`account_${index}`} label={t("account")} style={{ minWidth: "220px" }}>
                    <select value={line.account} onChange={(e) => updateLine(index, { account: e.target.value })}>
                      <option value="">—</option>
                      {options.accounts.map((a) => (
                        <option key={a.id} value={a.id}>{a.code} — {a.name}</option>
                      ))}
                    </select>
                  </FormField>
                </>
              )}
              {options.cost_centers.length > 0 && (
                <FormField name={`cost_center_${index}`} label={t("costCenter")}>
                  <select value={line.costCenter} onChange={(e) => updateLine(index, { costCenter: e.target.value })}>
                    <option value="">—</option>
                    {options.cost_centers.map((c) => (
                      <option key={c.id} value={c.id}>{c.code} — {c.name}</option>
                    ))}
                  </select>
                </FormField>
              )}
              <FormField name={`qty_${index}`} label={t("quantity")}>
                <input type="number" step="0.01" min="0.01" value={line.qty} onChange={(e) => updateLine(index, { qty: e.target.value })} style={{ width: "6rem" }} />
              </FormField>
              <FormField name={`unit_price_${index}`} label={t("unitPrice")}>
                <input type="number" step="0.01" min="0.01" value={line.unitPrice} onChange={(e) => updateLine(index, { unitPrice: e.target.value })} style={{ width: "9rem" }} />
              </FormField>
              <FormField name={`tax_code_${index}`} label={t("taxCode")}>
                <select value={line.taxCode} onChange={(e) => updateLine(index, { taxCode: e.target.value })}>
                  <option value="" disabled>—</option>
                  {options.tax_codes.map((c) => (
                    <option key={c.id} value={c.id}>{c.code} — {c.name} ({c.rate}%)</option>
                  ))}
                </select>
              </FormField>
              <FormField name={`vat_deductible_${index}`} label={t("billVatDeductible")}>
                <input type="checkbox" checked={line.vatDeductible} onChange={(e) => updateLine(index, { vatDeductible: e.target.checked })} />
              </FormField>
              {options.wht_codes.length > 0 && (
                <FormField name={`wht_code_${index}`} label={t("billWithholding")}>
                  <select value={line.whtCode} onChange={(e) => updateLine(index, { whtCode: e.target.value })}>
                    <option value="">{t("billNoWithholding")}</option>
                    {options.wht_codes.map((c) => (
                      <option key={c.id} value={c.id}>{c.code} — {c.name_ar} ({c.rate}%)</option>
                    ))}
                  </select>
                </FormField>
              )}
              {lines.length > 1 && (
                <button type="button" className="secondary" onClick={() => setLines((prev) => prev.filter((_, i) => i !== index))}>
                  {t("billRemoveLine")}
                </button>
              )}
            </div>
          ))}
        </div>
      </FormField>
      <button
        type="button"
        className="secondary"
        onClick={() =>
          setLines((prev) => [
            ...prev,
            emptyLine("expense", selectedSupplier?.default_expense_account ?? "", prev[prev.length - 1]?.taxCode ?? ""),
          ])
        }
      >
        {t("addLine")}
      </button>

      <FormField name="notes" label={t("notes")} error={fieldErr.notes}>
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} />
      </FormField>
      <p style={{ color: "var(--muted)" }}>{t("billTotalsAfterSave")}</p>

      <WarningsBanner warnings={error ? [error] : []} variant="error" />
      <div style={{ marginTop: "0.75rem" }}>
        <button className="primary" type="submit" disabled={saving}>{t("save")}</button>
        {onCancel && (
          <button type="button" className="secondary" style={{ marginInlineStart: "0.5rem" }} onClick={onCancel}>
            {t("cancel")}
          </button>
        )}
      </div>
    </form>
  );
}
