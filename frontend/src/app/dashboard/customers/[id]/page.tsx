"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { AttachmentPanel } from "@/components/AttachmentPanel";
import { useLocale } from "@/lib/i18n";
import type { CustomerParty, Invoice, Paginated } from "@/lib/types";

// 3.18 rule 2: every list screen leads to a detail screen with the
// record's data and its relations — for a customer, that's its
// invoices. AttachmentPanel (sprint 5.2) below; the record's own audit
// log (F10, CFO_REVIEW_1) is sprint 5.7.
export default function CustomerDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { t } = useLocale();
  const [customer, setCustomer] = useState<CustomerParty | null>(null);
  const [invoices, setInvoices] = useState<Invoice[]>([]);

  useEffect(() => {
    Promise.all([
      api.get<CustomerParty>(`/parties/customers/${id}/`),
      api.get<Paginated<Invoice>>(`/invoices/?customer=${id}`),
    ]).then(([customerData, invoiceData]) => {
      setCustomer(customerData);
      setInvoices(invoiceData.results);
    });
  }, [id]);

  if (!customer) return null;

  return (
    <div>
      <button className="secondary" onClick={() => router.push("/dashboard/customers")}>
        ← {t("back")}
      </button>

      <h1 style={{ marginTop: "1rem" }}>{customer.name}</h1>
      <p style={{ color: "var(--muted)" }}>{customer.code}</p>

      <div className="card">
        <h3>{t("customers")}</h3>
        <p>{t("phone")}: {customer.phone || "—"}</p>
        <p>{t("email")}: {customer.email || "—"}</p>
        <p>{t("taxNumber")}: {customer.tax_number || "—"}</p>
        <p>{t("creditLimit")}: {customer.credit_limit ?? "—"}</p>
        <p>{t("paymentTermsDays")}: {customer.payment_terms_days ?? "—"}</p>
      </div>

      <div className="card">
        <h3>{t("relatedInvoices")}</h3>
        {invoices.length === 0 ? (
          <p style={{ color: "var(--muted)" }}>{t("noData")}</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>{t("number")}</th>
                <th>{t("status")}</th>
                <th>{t("issueDate")}</th>
                <th>{t("total")}</th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((invoice) => (
                <tr key={invoice.id}>
                  <td>{invoice.number}</td>
                  <td>{t(invoice.status)}</td>
                  <td>{invoice.issue_date}</td>
                  <td>{invoice.total}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <AttachmentPanel targetType="party" targetId={customer.id} />
    </div>
  );
}
