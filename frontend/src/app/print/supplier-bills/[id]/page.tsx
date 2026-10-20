"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { Money } from "@/components/Money";
import { formatDate } from "@/lib/date";
import { amountInWordsAr } from "@/lib/numberToWordsAr";
import type { SupplierBill } from "@/lib/types";

const LINE_TYPE_LABEL: Record<string, string> = {
  service: "billLineService",
  expense: "billLineExpense",
  asset: "billLineAsset",
};

/** Sprint 8.1: the supplier bill as an internal printed record (our PINV
 * number, the supplier's own invoice number, lines and the server's
 * totals) — outside src/app/dashboard like every print page, so no
 * sidebar. Reads only the bill itself: the entity name is on it, so a
 * purchasing user without organization.view can print it too. */
export default function SupplierBillPrintPage() {
  const { id } = useParams<{ id: string }>();
  const { t } = useLocale();
  const [bill, setBill] = useState<SupplierBill | null>(null);

  useEffect(() => {
    api.get<SupplierBill>(`/purchasing/bills/${id}/`).then(setBill);
  }, [id]);

  if (!bill) return null;

  return (
    <div>
      <div className="print-actions">
        <button className="primary" onClick={() => window.print()}>{t("printButton")}</button>
      </div>
      <div className="print-page">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
          <div style={{ display: "flex", gap: "0.75rem", alignItems: "start" }}>
            <img src="/brand/cps-logo-horizontal.svg" alt="CPS" style={{ height: 48 }} />
            <h2 style={{ margin: 0 }}>{bill.legal_entity_name}</h2>
          </div>
          <div style={{ textAlign: "end" }}>
            <h2>{t("supplierBillDocType")}</h2>
            <p>{t("number")}: {bill.number}</p>
            <p>{t("billDate")}: {formatDate(bill.date, "form")}</p>
            <p>{t("dueDate")}: {bill.due_date ? formatDate(bill.due_date, "form") : "—"}</p>
          </div>
        </div>

        <hr style={{ margin: "1.5rem 0", border: "none", borderTop: "1px solid var(--border)" }} />

        <p><strong>{t("billSupplier")}:</strong> {bill.supplier_name}</p>
        <p><strong>{t("supplierInvoiceNumber")}:</strong> {bill.bill_number}</p>
        {bill.reference && <p><strong>{t("reference")}:</strong> {bill.reference}</p>}

        <table style={{ marginTop: "1rem" }}>
          <thead>
            <tr>
              <th>{t("billLineType")}</th>
              <th>{t("description")}</th>
              <th>{t("quantity")}</th>
              <th>{t("unitPrice")}</th>
              <th>{t("billLineNet")}</th>
              <th>{t("taxCode")}</th>
              <th>{t("billLineVat")}</th>
            </tr>
          </thead>
          <tbody>
            {bill.lines.map((line) => (
              <tr key={line.id}>
                <td>{t(LINE_TYPE_LABEL[line.line_type])}</td>
                <td>{line.line_type === "asset" ? line.asset_name : line.description || `${line.account_code} — ${line.account_name}`}</td>
                <td>{line.qty}</td>
                <td><Money amount={line.unit_price} /></td>
                <td><Money amount={line.net} /></td>
                <td>{line.tax_code_display} ({line.tax_rate}%)</td>
                <td><Money amount={line.tax_amount} /></td>
              </tr>
            ))}
          </tbody>
        </table>

        <table style={{ marginTop: "1rem", maxWidth: "460px" }}>
          <tbody>
            <tr><td>{t("billSubtotal")}</td><td><Money amount={bill.subtotal} currency={bill.currency} /></td></tr>
            <tr><td>{t("billDeductibleVat")}</td><td><Money amount={bill.deductible_tax} currency={bill.currency} /></td></tr>
            <tr><td>{t("billCapitalizedVat")}</td><td><Money amount={bill.capitalized_tax} currency={bill.currency} /></td></tr>
            <tr><td>{t("billReverseChargeVat")}</td><td><Money amount={bill.reverse_charge_tax} currency={bill.currency} /></td></tr>
            <tr><td>{t("billExpectedWithholding")}</td><td><Money amount={bill.wht_expected} currency={bill.currency} /></td></tr>
          </tbody>
        </table>

        <p style={{ marginTop: "1rem", fontSize: "1.2rem" }}><strong>{t("billTotal")}: <Money amount={bill.total} currency={bill.currency} /></strong></p>
        <p>{t("amountInWords")}: {amountInWordsAr(bill.total, bill.currency)}</p>

        <div className="print-signatures">
          <div>{t("signatureAccountant")}</div>
          <div>{t("signatureManager")}</div>
        </div>
      </div>
    </div>
  );
}
