"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, generalError } from "@/lib/api";
import { AttachmentPanel } from "@/components/AttachmentPanel";
import { Money } from "@/components/Money";
import { StatusBadge } from "@/components/StatusBadge";
import { useLocale } from "@/lib/i18n";
import type { OpeningBalanceEntry, ReadinessItem } from "@/lib/types";

const LEVEL_COLOR: Record<ReadinessItem["level"], string> = {
  block: "var(--status-void)",
  warn: "var(--status-pending)",
  info: "var(--muted)",
};

export default function OpeningBalanceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { t } = useLocale();
  const [entry, setEntry] = useState<OpeningBalanceEntry | null>(null);
  const [readiness, setReadiness] = useState<ReadinessItem[] | null>(null);
  const [attestation, setAttestation] = useState("");
  const [rejectReason, setRejectReason] = useState("");
  const [showReject, setShowReject] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    api.get<OpeningBalanceEntry>(`/opening-balances/${id}/`).then(setEntry);
  };

  useEffect(load, [id]);

  if (!entry) return null;

  const checkReadiness = async () => {
    const data = await api.get<{ items: ReadinessItem[] }>(`/opening-balances/${id}/readiness/`);
    setReadiness(data.items);
  };

  const runAction = async (action: string, body?: Record<string, unknown>) => {
    setError(null);
    try {
      await api.post(`/opening-balances/${id}/${action}/`, body);
      setAttestation("");
      setRejectReason("");
      setShowReject(false);
      load();
    } catch (err) {
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const debitTotal = entry.lines.reduce((sum, l) => sum + parseFloat(l.debit_base), 0);
  const creditTotal = entry.lines.reduce((sum, l) => sum + parseFloat(l.credit_base), 0);

  return (
    <div>
      <button className="secondary" onClick={() => router.push("/dashboard/accounting/opening-balances")}>
        ← {t("back")}
      </button>

      <h1 style={{ marginTop: "1rem" }}>
        {entry.legal_entity_name} — {t(entry.kind)} <StatusBadge status={entry.status} />
      </h1>

      <div className="card">
        <p>{t("openingDate")}: {entry.opening_date}</p>
        {entry.attestation_text && <p>{t("attestationText")}: {entry.attestation_text}</p>}
        {entry.journal_entry && (
          <p>
            {t("post")}: <a href={`/dashboard/accounting/journal-entries/${entry.journal_entry}`}>{t("viewDetails")}</a>
          </p>
        )}
      </div>

      <div className="card">
        <h3>{t("lines")}</h3>
        <table>
          <thead>
            <tr>
              <th>{t("account")}</th>
              <th>{t("party")}</th>
              <th>{t("debitFc")}</th>
              <th>{t("creditFc")}</th>
            </tr>
          </thead>
          <tbody>
            {entry.lines.map((line) => (
              <tr key={line.id}>
                <td>{line.account_code} — {line.account_name}</td>
                <td>{line.party_name}</td>
                <td>{line.debit_base !== "0.00" ? <Money amount={line.debit_base} /> : ""}</td>
                <td>{line.credit_base !== "0.00" ? <Money amount={line.credit_base} /> : ""}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={2}>{t("difference")}</td>
              <td><Money amount={String(debitTotal)} /></td>
              <td><Money amount={String(creditTotal)} /></td>
            </tr>
          </tfoot>
        </table>
      </div>

      <div className="card">
        <button className="secondary" onClick={checkReadiness}>{t("checkReadiness")}</button>
        {readiness && (
          <ul style={{ marginTop: "0.75rem" }}>
            {readiness.map((item, i) => (
              <li key={i} style={{ color: LEVEL_COLOR[item.level] }}>
                [{item.level.toUpperCase()}] {item.message}
              </li>
            ))}
            {readiness.length === 0 && <li>{t("balanced")} ✓</li>}
          </ul>
        )}
      </div>

      {error && <p className="error-text">{error}</p>}

      {entry.status === "draft" && (
        <div className="card">
          <button className="primary" onClick={() => runAction("submit")}>{t("submitForApproval")}</button>
        </div>
      )}

      {entry.status === "pending_approval" && (
        <div className="card">
          <div className="form-field" style={{ maxWidth: "480px" }}>
            <label>{t("attestationText")}</label>
            <textarea value={attestation} onChange={(e) => setAttestation(e.target.value)} rows={3} />
          </div>
          <button
            className="primary"
            style={{ marginTop: "0.5rem" }}
            onClick={() => runAction("approve", { attestation_text: attestation })}
          >
            {t("approveWithAttestation")}
          </button>
          <button
            className="secondary"
            style={{ marginInlineStart: "0.5rem" }}
            onClick={() => runAction("withdraw")}
          >
            {t("withdraw")}
          </button>
          <button
            className="secondary"
            style={{ marginInlineStart: "0.5rem" }}
            onClick={() => setShowReject((v) => !v)}
          >
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
          <button
            className="secondary"
            onClick={() =>
              router.push(`/dashboard/accounting/opening-balances?entity=${entry.legal_entity}&kind=adjustment`)
            }
          >
            {t("createAdjustment")}
          </button>
        </div>
      )}

      <AttachmentPanel targetType="opening_balance" targetId={entry.id} />
    </div>
  );
}
