"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import type { PendingApproval } from "@/lib/types";

const DOC_TYPE_LABEL: Record<PendingApproval["doc_type"], string> = {
  journal_entry: "journalEntryDocType",
  invoice: "invoiceDocType",
  voucher_receipt: "voucherReceiptDocType",
  voucher_payment: "voucherPaymentDocType",
  voucher_settlement: "voucherSettlementDocType",
};

const DOC_TYPE_PATH: Record<PendingApproval["doc_type"], string> = {
  journal_entry: "journal-entries",
  invoice: "invoices",
  voucher_receipt: "vouchers",
  voucher_payment: "vouchers",
  voucher_settlement: "vouchers",
};

export default function ApprovalInboxPage() {
  const { t } = useLocale();
  const [rows, setRows] = useState<PendingApproval[]>([]);

  const load = async () => {
    const data = await api.get<PendingApproval[]>("/approvals/pending/");
    setRows(data);
  };

  useEffect(() => {
    load();
  }, []);

  const approve = async (row: PendingApproval) => {
    await api.post(`/${DOC_TYPE_PATH[row.doc_type]}/${row.id}/approve/`);
    load();
  };

  return (
    <div>
      <h1>{t("approvalInbox")}</h1>
      {rows.length === 0 ? (
        <p style={{ color: "var(--muted)" }}>{t("noPendingApprovals")}</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>{t("docType")}</th>
              <th>{t("number")}</th>
              <th>{t("date")}</th>
              <th>{t("details")}</th>
              <th>{t("amountBase")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.doc_type}-${row.id}`}>
                <td>{t(DOC_TYPE_LABEL[row.doc_type])}</td>
                <td>{row.number}</td>
                <td>{row.date}</td>
                <td>{row.description}</td>
                <td>{row.amount_base}</td>
                <td>
                  <button className="secondary" onClick={() => approve(row)}>
                    {t("approve")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
