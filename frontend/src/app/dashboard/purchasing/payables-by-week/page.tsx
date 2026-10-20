"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { FormField } from "@/components/FormField";
import { Money } from "@/components/Money";
import { ErrorState, apiErrorKind, type ApiErrorKind } from "@/components/ScreenErrors";
import { formatDate } from "@/lib/date";
import type { PayablesByWeek, SupplierBillFormOptions } from "@/lib/types";

/** Sprint 8.2: «مستحقات الدفع بالأسبوع» — open supplier-bill balances (base
 * currency, each bill's own rate) by the week their due date falls in:
 * overdue, this week and the next seven, later. A failed load is named
 * (block 8.0.2), never shown as weeks with nothing due. */
export default function PayablesByWeekPage() {
  const { t } = useLocale();
  const [options, setOptions] = useState<SupplierBillFormOptions | null>(null);
  const [legalEntityId, setLegalEntityId] = useState("");
  const [asOf, setAsOf] = useState(() => new Date().toISOString().slice(0, 10));
  const [report, setReport] = useState<PayablesByWeek | null>(null);
  const [loadError, setLoadError] = useState<ApiErrorKind | null>(null);

  useEffect(() => {
    api.get<SupplierBillFormOptions>("/purchasing/bills/form-options/").then(setOptions);
  }, []);

  useEffect(() => {
    const params = new URLSearchParams({ as_of: asOf });
    if (legalEntityId) params.set("legal_entity", legalEntityId);
    setReport(null);
    setLoadError(null);
    api
      .get<PayablesByWeek>(`/purchasing/payables-by-week/?${params.toString()}`)
      .then(setReport)
      .catch((err) => setLoadError(apiErrorKind(err) ?? "server-error"));
  }, [legalEntityId, asOf]);

  const bucketLabel = (bucket: PayablesByWeek["buckets"][number], index: number) => {
    if (bucket.key === "overdue") return t("payablesOverdue");
    if (bucket.key === "later") return `${t("payablesLater")} (${formatDate(bucket.start!, "form")} +)`;
    return `${t("payablesWeek")} ${index}: ${formatDate(bucket.start!, "form")} – ${formatDate(bucket.end!, "form")}`;
  };

  return (
    <div>
      <h1>{t("payablesByWeekNav")}</h1>
      <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
        <FormField name="list_entity_filter" label={t("entityFilter")}>
          <select value={legalEntityId} onChange={(e) => setLegalEntityId(e.target.value)}>
            <option value="">{t("allEntities")}</option>
            {options?.legal_entities.map((entity) => (
              <option key={entity.id} value={entity.id}>{entity.code} — {entity.name}</option>
            ))}
          </select>
        </FormField>
        <FormField name="as_of" label={t("asOf")}>
          <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
        </FormField>
      </div>

      {loadError && <ErrorState kind={loadError} />}
      {report && (
        <div data-testid="payables-by-week">
          <p><strong>{t("total")}: <Money amount={report.total} /></strong></p>
          {report.buckets.map((bucket, i) => (
            <div key={bucket.key} className="card" data-bucket={bucket.key}>
              <h3 style={{ marginTop: 0 }}>
                {bucketLabel(bucket, i)} — <Money amount={bucket.total} />
              </h3>
              {bucket.bills.length === 0 ? (
                <p style={{ color: "var(--muted)" }}>—</p>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>{t("number")}</th>
                      <th>{t("supplierInvoiceNumber")}</th>
                      <th>{t("billSupplier")}</th>
                      <th>{t("dueDate")}</th>
                      <th>{t("balanceDue")}</th>
                      <th>{t("expensesTotalBase")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bucket.bills.map((bill) => (
                      <tr key={bill.id}>
                        <td><Link href={`/dashboard/purchasing/bills/${bill.id}`}>{bill.number}</Link></td>
                        <td>{bill.bill_number}</td>
                        <td>{bill.supplier_name}</td>
                        <td>{formatDate(bill.due_date, "form")}</td>
                        <td><Money amount={bill.balance_fc} currency={bill.currency} /></td>
                        <td><Money amount={bill.amount_base} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
