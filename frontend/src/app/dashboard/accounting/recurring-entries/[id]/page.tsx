"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, generalError } from "@/lib/api";
import { Money } from "@/components/Money";
import { StatusBadge } from "@/components/StatusBadge";
import { useLocale } from "@/lib/i18n";
import type { RecurringEntry, RecurringInstallmentStatus } from "@/lib/types";

const INSTALLMENT_STATUS_LABEL: Record<RecurringInstallmentStatus, string> = {
  due: "dueStatus",
  generated: "generatedStatus",
  skipped: "skippedStatus",
  cancelled: "cancelled",
};

// Sprint 6.5.15 (UAT item 7): see the identical helper on the asset
// detail page — "due" only reads "مستحق" once its own date has
// actually arrived, "مجدول" (scheduled) before that.
function installmentStatusLabelKey(status: RecurringInstallmentStatus, dueDate: string): string {
  if (status === "due" && dueDate > new Date().toISOString().slice(0, 10)) return "scheduledStatus";
  return INSTALLMENT_STATUS_LABEL[status];
}

export default function RecurringEntryDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { t } = useLocale();
  const [entry, setEntry] = useState<RecurringEntry | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [showReject, setShowReject] = useState(false);

  const load = () => {
    api.get<RecurringEntry>(`/recurring-entries/${id}/`).then(setEntry);
  };

  useEffect(load, [id]);

  if (!entry) return null;

  const runAction = async (action: string, body?: Record<string, unknown>) => {
    setError(null);
    try {
      await api.post(`/recurring-entries/${id}/${action}/`, body);
      setShowReject(false);
      setRejectReason("");
      load();
    } catch (err) {
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const regenerate = async (installmentId: string) => {
    await api.post(`/recurring-installments/${installmentId}/regenerate/`);
    load();
  };

  return (
    <div>
      <button className="secondary" onClick={() => router.push("/dashboard/accounting/recurring-entries")}>
        ← {t("back")}
      </button>

      <h1 style={{ marginTop: "1rem" }}>
        {entry.number || `(${t("draft")})`} — {entry.description} <StatusBadge status={entry.status} />
      </h1>

      <div className="card">
        <p>{t("legalEntity")}: {entry.legal_entity_name}</p>
        {/* Sprint 6.5.15 (UAT item 7): to_account is always the DEBIT
            side, from_account always CREDIT (apps.accounting.recurring.
            _generate_one) — a depreciation schedule's own two accounts
            are always expense (debit) / accumulated depreciation
            (credit) specifically, so it gets its own clearer labels
            instead of the generic "من حساب/إلى حساب" every other
            recurring entry kind still uses. */}
        <p>
          {t(entry.kind === "depreciation" ? "depreciationDebitAccount" : "toAccount")}:{" "}
          {entry.to_account_code} — {entry.to_account_name}
        </p>
        <p>
          {t(entry.kind === "depreciation" ? "depreciationCreditAccount" : "fromAccount")}:{" "}
          {entry.from_account_code} — {entry.from_account_name}
        </p>
        <p>{t("total")}: <Money amount={entry.total_amount_base} /></p>
        <p>{t("installmentsCount")}: {entry.installments_count}</p>
      </div>

      {error && <p className="error-text">{error}</p>}

      {entry.status === "draft" && (
        <div className="card">
          <button className="primary" onClick={() => runAction("submit")}>{t("submitForApproval")}</button>
        </div>
      )}

      {entry.status === "pending_approval" && (
        <div className="card">
          <button className="primary" onClick={() => runAction("approve")}>{t("approve")}</button>
          <button className="secondary" style={{ marginInlineStart: "0.5rem" }} onClick={() => runAction("withdraw")}>
            {t("withdraw")}
          </button>
          <button className="secondary" style={{ marginInlineStart: "0.5rem" }} onClick={() => setShowReject((v) => !v)}>
            {t("reject")}
          </button>
          {showReject && (
            <div style={{ marginTop: "0.5rem" }}>
              <input
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                placeholder={t("reason")}
                style={{ minWidth: "260px" }}
              />
              <button
                className="secondary"
                style={{ marginInlineStart: "0.5rem" }}
                onClick={() => runAction("reject", { reason: rejectReason })}
              >
                {t("save")}
              </button>
            </div>
          )}
        </div>
      )}

      {entry.status === "approved" && (
        <div className="card">
          <button className="secondary" onClick={() => runAction("cancel")}>{t("cancel")}</button>
        </div>
      )}

      <div className="card">
        <h3>{t("installments")}</h3>
        <table>
          <thead>
            <tr>
              <th>{t("seq")}</th>
              <th>{t("dueDate")}</th>
              <th>{t("amount")}</th>
              <th>{t("status")}</th>
              <th>{t("post")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {entry.installments.map((installment) => (
              <tr key={installment.id}>
                <td>{installment.seq}</td>
                <td>{installment.due_date}</td>
                <td><Money amount={installment.amount_base} /></td>
                <td>
                  {t(installmentStatusLabelKey(installment.status, installment.due_date))}
                  {installment.status === "skipped" && installment.skip_reason && (
                    <div style={{ color: "var(--muted)", fontSize: "0.8rem" }}>{installment.skip_reason}</div>
                  )}
                </td>
                <td>
                  {installment.journal_entry && (
                    <a href={`/dashboard/accounting/journal-entries/${installment.journal_entry}`}>
                      {t("viewDetails")}
                    </a>
                  )}
                </td>
                <td>
                  {installment.status === "skipped" && (
                    <button className="secondary" onClick={() => regenerate(installment.id)}>
                      {t("regenerate")}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
