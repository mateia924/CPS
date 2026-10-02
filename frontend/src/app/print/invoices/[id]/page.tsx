"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { Money } from "@/components/Money";
import { formatDate } from "@/lib/date";
import { amountInWordsAr } from "@/lib/numberToWordsAr";
import type { Invoice, LegalEntity, TaxCode, Paginated } from "@/lib/types";

// Sprint 5.6 (block 5.6): a plain route outside src/app/dashboard —
// no sidebar, just the root layout (providers only), so it prints
// full-bleed. Calls POST /invoices/{id}/deliver/ once on load (CFO_
// REVIEW_1 C7 groundwork — delivered_at is set-once, so a second visit
// here is a no-op server-side).
export default function InvoicePrintPage() {
  const { id } = useParams<{ id: string }>();
  const { t } = useLocale();
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [entity, setEntity] = useState<LegalEntity | null>(null);
  const [taxCodes, setTaxCodes] = useState<TaxCode[]>([]);

  useEffect(() => {
    api.get<Invoice>(`/invoices/${id}/`).then(async (inv) => {
      setInvoice(inv);
      const [entityData, taxData] = await Promise.all([
        api.get<LegalEntity>(`/legal-entities/${inv.legal_entity}/`),
        api.get<Paginated<TaxCode>>("/tax-codes/"),
      ]);
      setEntity(entityData);
      setTaxCodes(taxData.results);
      api.post(`/invoices/${inv.id}/deliver/`).catch(() => undefined);
    });
  }, [id]);

  if (!invoice || !entity) return null;

  const profile = entity.effective_profile;
  const addressLine = [profile.building_number, profile.street, profile.district, profile.city, profile.postal_code]
    .filter(Boolean)
    .join("، ");

  // Accumulated as numbers, formatted only at render time via <Money>.
  const taxSummary = new Map<string, { code: string; rate: string; base: number; tax: number }>();
  for (const line of invoice.lines) {
    const key = line.tax_code_display;
    const existing = taxSummary.get(key) || { code: key, rate: line.tax_rate, base: 0, tax: 0 };
    existing.base += parseFloat(line.line_subtotal);
    existing.tax += parseFloat(line.line_tax);
    taxSummary.set(key, existing);
  }

  const isSimplified = invoice.customer_party_type === "individual";

  return (
    <div>
      <div className="print-actions">
        <button className="primary" onClick={() => window.print()}>{t("printButton")}</button>
      </div>
      <div className="print-page">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
          <div style={{ display: "flex", gap: "0.75rem", alignItems: "start" }}>
            <img src="/brand/cps-logo-horizontal.svg" alt="CPS" style={{ height: 48 }} />
            <div>
            <h2 style={{ margin: 0 }}>{entity.name}</h2>
            {profile.commercial_registration && <p>{t("commercialRegistration")}: {profile.commercial_registration}</p>}
            {entity.tax_number && <p>{t("taxNumber")}: {entity.tax_number}</p>}
            {addressLine && <p>{addressLine}</p>}
            {profile.phone && <p>{profile.phone}</p>}
            </div>
          </div>
          <div style={{ textAlign: "end" }}>
            <h2>{t(isSimplified ? "simplifiedTaxInvoiceTitle" : "taxInvoiceTitle")}</h2>
            <p>{t("number")}: {invoice.number}</p>
            <p>{t("issueDate")}: {formatDate(invoice.issue_date, "form")}</p>
          </div>
        </div>

        <hr style={{ margin: "1.5rem 0", border: "none", borderTop: "1px solid var(--border)" }} />

        <p><strong>{t("customer")}:</strong> {invoice.customer_name}</p>

        <table style={{ marginTop: "1rem" }}>
          <thead>
            <tr>
              <th>{t("product")}</th>
              <th>{t("quantity")}</th>
              <th>{t("unitPrice")}</th>
              <th>{t("taxCode")}</th>
              <th>{t("subtotal")}</th>
              <th>{t("taxTotal")}</th>
              <th>{t("total")}</th>
            </tr>
          </thead>
          <tbody>
            {invoice.lines.map((line) => (
              <tr key={line.id}>
                <td>{line.description}</td>
                <td>{line.quantity}</td>
                <td><Money amount={line.unit_price} /></td>
                <td>{line.tax_code_display}</td>
                <td><Money amount={line.line_subtotal} /></td>
                <td><Money amount={line.line_tax} /></td>
                <td><Money amount={line.line_total} /></td>
              </tr>
            ))}
          </tbody>
        </table>

        <table style={{ marginTop: "1rem", maxWidth: "400px" }}>
          <thead>
            <tr>
              <th>{t("taxSummaryByCode")}</th>
              <th>{t("subtotal")}</th>
              <th>{t("taxTotal")}</th>
            </tr>
          </thead>
          <tbody>
            {[...taxSummary.values()].map((row) => (
              <tr key={row.code}>
                <td>{row.code} ({row.rate}%)</td>
                <td><Money amount={row.base} /></td>
                <td><Money amount={row.tax} /></td>
              </tr>
            ))}
          </tbody>
        </table>

        <p style={{ marginTop: "1rem", fontSize: "1.2rem" }}><strong>{t("total")}: <Money amount={invoice.total} currency={invoice.currency} /></strong></p>
        <p>{t("amountInWords")}: {amountInWordsAr(invoice.total, invoice.currency)}</p>

        <div className="print-signatures">
          <div>{t("signatureAccountant")}</div>
          <div>{t("signatureManager")}</div>
        </div>
      </div>
    </div>
  );
}
