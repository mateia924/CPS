"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { api, generalError } from "@/lib/api";
import { AttachmentPanel } from "@/components/AttachmentPanel";
import { ChangeHistoryTab } from "@/components/ChangeHistoryTab";
import { Money } from "@/components/Money";
import { StatusBadge } from "@/components/StatusBadge";
import { useLocale } from "@/lib/i18n";
import type { Voucher } from "@/lib/types";

const PAYMENT_METHOD_LABEL: Record<string, string> = {
  cash: "paymentMethodCash",
  bank_transfer: "paymentMethodBankTransfer",
  cheque: "paymentMethodCheque",
  card: "paymentMethodCard",
  other: "paymentMethodOther",
};

const DOC_TYPE_LABEL: Record<string, string> = {
  receipt: "voucherReceiptDocType",
  payment: "voucherPaymentDocType",
  settlement: "voucherSettlementDocType",
};

// Sprint 5.6 (block 5.6): one detail screen for all three voucher
// types (same "one engine" principle as the backend and the list/form
// screen above) — data, lines, the linked journal entry, allocations,
// AttachmentPanel, and every status-transition button gated by status.
export default function VoucherDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { t } = useLocale();
  const [voucher, setVoucher] = useState<Voucher | null>(null);
  const [reasonMode, setReasonMode] = useState<"reject" | "reverse" | null>(null);
  const [reasonText, setReasonText] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    api.get<Voucher>(`/vouchers/${id}/`).then(setVoucher);
  };

  useEffect(load, [id]);

  if (!voucher) return null;

  const runAction = async (action: string) => {
    setError(null);
    try {
      await api.post(`/vouchers/${voucher.id}/${action}/`);
      load();
    } catch (err) {
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const submitReason = async () => {
    if (!reasonMode) return;
    setError(null);
    try {
      await api.post(`/vouchers/${voucher.id}/${reasonMode}/`, { reason: reasonText });
      setReasonMode(null);
      setReasonText("");
      load();
    } catch (err) {
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  return (
    <div>
      <button className="secondary" onClick={() => router.push("/dashboard/treasury/vouchers/receipt")}>
        ← {t("back")}
      </button>

      <h1 style={{ marginTop: "1rem" }}>
        {t(DOC_TYPE_LABEL[voucher.voucher_type] || "vouchersTab")} {voucher.number || `(${t("draft")})`}
      </h1>
      <p><StatusBadge status={voucher.status} /></p>

      <div className="card">
        <p>{t("voucherDate")}: {voucher.date}</p>
        <p>{t("treasuryAccount")}: {voucher.treasury_name}</p>
        {voucher.counter_treasury_name && <p>{t("destinationAccount")}: {voucher.counter_treasury_name}</p>}
        <p>{t(voucher.voucher_type === "receipt" ? "receivedFrom" : "paidTo")}: {voucher.party_name || voucher.payee_name || "—"}</p>
        <p>{t("paymentMethod")}: {t(PAYMENT_METHOD_LABEL[voucher.payment_method] || voucher.payment_method)}</p>
        <p>{t("reference")}: {voucher.reference || "—"}</p>
        <p>{t("description")}: {voucher.description || "—"}</p>
        <p>{t("grandTotal")}: <Money amount={voucher.total_fc} currency={voucher.currency} /> (<Money amount={voucher.total_base} />)</p>
        {voucher.exchange_rate_overridden && <p style={{ color: "var(--muted)" }}>{t("exchangeRateLabel")}: {voucher.exchange_rate}</p>}
        {voucher.journal_entry_id ? (
          <p>
            {t("relatedJournalEntry")}:{" "}
            <Link href={`/dashboard/accounting/journal-entries/${voucher.journal_entry_id}`}>
              {voucher.journal_entry_number || voucher.journal_entry_id}
            </Link>
          </p>
        ) : (
          <p>{t("relatedJournalEntry")}: —</p>
        )}
      </div>

      {voucher.lines.length > 0 && (
        <div className="card">
          <h3>{t("payments")}</h3>
          <table>
            <thead>
              <tr>
                <th>{t("lineType")}</th>
                <th>{t("description")}</th>
                <th>{t("amount")}</th>
              </tr>
            </thead>
            <tbody>
              {voucher.lines.map((line) => (
                <tr key={line.id}>
                  <td>{t(`${line.line_type === "invoice" ? "invoiceLineType" : line.line_type === "on_account" ? "onAccountLineType" : "accountLineType"}`)}</td>
                  <td>{line.description || "—"}</td>
                  <td><Money amount={line.amount_fc} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {error && <p className="error-text">{error}</p>}

      {reasonMode ? (
        <div className="card">
          <h3>{reasonMode === "reject" ? t("rejectReason") : t("confirmReverseVoucher")}</h3>
          <input value={reasonText} onChange={(e) => setReasonText(e.target.value)} style={{ minWidth: "300px" }} />
          <div style={{ marginTop: "0.75rem" }}>
            <button className="primary" onClick={submitReason}>{t("save")}</button>
            <button type="button" className="secondary" style={{ marginInlineStart: "0.5rem" }} onClick={() => { setReasonMode(null); setReasonText(""); }}>{t("cancel")}</button>
          </div>
        </div>
      ) : (
        <div className="card">
          {voucher.status === "draft" && (
            <button className="primary" onClick={() => runAction("post")}>{t("postVoucher")}</button>
          )}
          {voucher.status === "pending_approval" && (
            <>
              <button className="primary" onClick={() => runAction("approve")}>{t("approveVoucher")}</button>
              <button className="secondary" style={{ marginInlineStart: "0.5rem" }} onClick={() => setReasonMode("reject")}>{t("reject")}</button>
              <button className="secondary" style={{ marginInlineStart: "0.5rem" }} onClick={() => runAction("withdraw")}>{t("withdraw")}</button>
            </>
          )}
          {voucher.status === "posted" && (
            <>
              <button className="secondary" onClick={() => setReasonMode("reverse")}>{t("reverse")}</button>
              <Link href={`/print/vouchers/${voucher.id}`} className="secondary" style={{ marginInlineStart: "0.5rem" }} target="_blank">
                {t("printButton")}
              </Link>
            </>
          )}
        </div>
      )}

      <AttachmentPanel targetType="voucher" targetId={voucher.id} />
      <ChangeHistoryTab targetType="voucher" targetId={voucher.id} />
    </div>
  );
}
