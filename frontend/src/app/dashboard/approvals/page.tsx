"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import type { PendingApproval } from "@/lib/types";

// Sprint 6.3 (decision 8): opening_balance's approve requires a written
// attestation (>= 20 chars) the generic one-click flow below has no
// field for — those rows route to their own detail screen (which has
// the attestation textarea) instead of a blind POST.
const REQUIRES_DETAIL_SCREEN = new Set<PendingApproval["doc_type"]>(["opening_balance"]);

const DOC_TYPE_LABEL: Record<PendingApproval["doc_type"], string> = {
  journal_entry: "journalEntryDocType",
  invoice: "invoiceDocType",
  voucher_receipt: "voucherReceiptDocType",
  voucher_payment: "voucherPaymentDocType",
  voucher_settlement: "voucherSettlementDocType",
  iban_change: "ibanChangeDocType",
  opening_balance: "openingBalanceDocType",
};

// Sprint 6.3: fixes a pre-existing gap (sprint 5.5) — an "iban_change"
// row's approve button called POST /undefined/{id}/approve/ since this
// map never had an entry for it; opening_balance joins it now.
const DOC_TYPE_PATH: Record<PendingApproval["doc_type"], string> = {
  journal_entry: "journal-entries",
  invoice: "invoices",
  voucher_receipt: "vouchers",
  voucher_payment: "vouchers",
  voucher_settlement: "vouchers",
  iban_change: "iban-requests",
  opening_balance: "opening-balances",
};

export default function ApprovalInboxPage() {
  const { t } = useLocale();
  const router = useRouter();
  const [rows, setRows] = useState<PendingApproval[]>([]);

  const load = async () => {
    const data = await api.get<PendingApproval[]>("/approvals/pending/");
    setRows(data);
  };

  useEffect(() => {
    load();
  }, []);

  const approve = async (row: PendingApproval) => {
    if (REQUIRES_DETAIL_SCREEN.has(row.doc_type)) {
      router.push(`/dashboard/accounting/${DOC_TYPE_PATH[row.doc_type]}/${row.id}`);
      return;
    }
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
                    {REQUIRES_DETAIL_SCREEN.has(row.doc_type) ? t("viewDetails") : t("approve")}
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
