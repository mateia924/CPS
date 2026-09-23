"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { AttachmentPanel } from "@/components/AttachmentPanel";
import { StatusBadge } from "@/components/StatusBadge";
import { useLocale } from "@/lib/i18n";
import type { Invoice } from "@/lib/types";

// Sprint 5.6 (block 5.6): "تفاصيل الفاتورة: قسم 'السدادات' (التخصيصات)
// + الرصيد + زر '+ سند قبض' مجهّز بالعميل والفاتورة والرصيد" — the
// first invoice detail page this project has ever had (3.5 built one
// for customers/employees only; invoices/journal-entries stayed list-
// only until now, per that sprint's own scope decision).
export default function InvoiceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { t } = useLocale();
  const [invoice, setInvoice] = useState<Invoice | null>(null);

  useEffect(() => {
    api.get<Invoice>(`/invoices/${id}/`).then(setInvoice);
  }, [id]);

  if (!invoice) return null;

  const quickReceiptHref =
    `/dashboard/treasury/vouchers/receipt?party=${invoice.customer}&party_role=customer` +
    `&invoice=${invoice.id}&amount_fc=${invoice.balance_fc}`;

  return (
    <div>
      <button className="secondary" onClick={() => router.push("/dashboard/invoices")}>
        ← {t("back")}
      </button>

      <h1 style={{ marginTop: "1rem" }}>{invoice.number || `(${t("draft")})`}</h1>
      <p><StatusBadge status={invoice.status} /></p>

      <div className="card">
        <p>{t("customer")}: {invoice.customer_name}</p>
        <p>{t("legalEntity")}: {invoice.legal_entity_name}</p>
        <p>{t("issueDate")}: {invoice.issue_date}</p>
        {invoice.due_date && <p>{t("dueDate")}: {invoice.due_date}</p>}
        <p>{t("total")}: {invoice.total} {invoice.currency}</p>
        {invoice.status === "issued" && (
          <Link href={`/print/invoices/${invoice.id}`} className="secondary" target="_blank">
            {t("printButton")}
          </Link>
        )}
      </div>

      <div className="card">
        <h3>{t("payments")}</h3>
        <p>{t("total")}: {invoice.total} {invoice.currency}</p>
        <p>{t("balanceDue")}: {invoice.balance_fc} {invoice.currency}</p>
        <p>{t("status")}: {t(invoice.payment_status)}</p>
        {invoice.status === "issued" && parseFloat(invoice.balance_fc) > 0 && (
          <Link href={quickReceiptHref} className="primary" style={{ display: "inline-block", marginTop: "0.5rem" }}>
            {t("quickReceiptFor")}
          </Link>
        )}
      </div>

      <AttachmentPanel targetType="invoice" targetId={invoice.id} />
    </div>
  );
}
