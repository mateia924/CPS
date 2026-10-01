"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, generalError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { AttachmentPanel } from "@/components/AttachmentPanel";
import { FormField } from "@/components/FormField";
import { Money } from "@/components/Money";
import { StatusBadge } from "@/components/StatusBadge";
import { WarningsBanner } from "@/components/WarningsBanner";
import {
  EMPTY_LINE,
  linesToPayload,
  OpeningBalanceLinesEditor,
  type LineDraft,
} from "@/components/OpeningBalanceLinesEditor";
import { useLocale } from "@/lib/i18n";
import type {
  AccountTreeNode,
  CostCenter,
  OpeningBalanceEntry,
  OpeningBalanceLine,
  Paginated,
  Party,
  ReadinessItem,
} from "@/lib/types";

/** The backend's own OpeningBalanceLine shape (committed, snake_case
 * money strings) -> the shared editor's LineDraft shape (camelCase
 * drafts, same as a freshly-typed row on the create screen) — the
 * exact inverse of OpeningBalanceLinesEditor's own linesToPayload. */
function lineToDraft(line: OpeningBalanceLine): LineDraft {
  return {
    mode: line.party ? "party" : "account",
    account: line.account ?? "",
    party: line.party ?? "",
    partyRole: line.party_role,
    costCenter: line.cost_center ?? "",
    currency: line.currency,
    exchangeRate: line.exchange_rate,
    debitFc: line.debit_fc === "0.00" ? "" : line.debit_fc,
    creditFc: line.credit_fc === "0.00" ? "" : line.credit_fc,
    openItems: (line.open_items ?? []).map((item) => ({ ref: item.ref, date: item.date, amountFc: item.amount_fc })),
    notes: line.notes,
  };
}

const LEVEL_COLOR: Record<ReadinessItem["level"], string> = {
  block: "var(--status-void)",
  warn: "var(--status-pending)",
  info: "var(--muted)",
};

export default function OpeningBalanceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { t } = useLocale();
  const { me } = useAuth();
  const [entry, setEntry] = useState<OpeningBalanceEntry | null>(null);
  const [readiness, setReadiness] = useState<ReadinessItem[] | null>(null);
  const [attestation, setAttestation] = useState("");
  const [rejectReason, setRejectReason] = useState("");
  const [showReject, setShowReject] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Sprint 6.6.3d: picker data for the draft-only lines editor below —
  // same three endpoints the create screen already loads.
  const [accounts, setAccounts] = useState<AccountTreeNode[]>([]);
  const [parties, setParties] = useState<Party[]>([]);
  const [costCenters, setCostCenters] = useState<CostCenter[]>([]);
  const [editLines, setEditLines] = useState<LineDraft[]>([]);
  const showCostCenterUI = !!me && me.features.cost_centers;

  const load = () => {
    api.get<OpeningBalanceEntry>(`/opening-balances/${id}/`).then(setEntry);
  };

  useEffect(load, [id]);

  useEffect(() => {
    (async () => {
      const [tree, partyData] = await Promise.all([
        api.get<AccountTreeNode[]>("/accounts/tree/"),
        api.get<Paginated<Party>>("/parties/"),
      ]);
      setAccounts(tree);
      setParties(partyData.results);
      if (showCostCenterUI) {
        const ccData = await api.get<Paginated<CostCenter>>("/cost-centers/");
        setCostCenters(ccData.results);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showCostCenterUI]);

  // Sprint 6.6.3d (UAT 6 finding A): re-derive the editable draft from
  // whatever the server just returned — on first load, and again after
  // every successful "save lines" (which returns the authoritative,
  // resolved line set, e.g. a party line's actual sub-ledger account).
  useEffect(() => {
    if (entry && entry.status === "draft") {
      setEditLines(entry.lines.length ? entry.lines.map(lineToDraft) : [{ ...EMPTY_LINE }, { ...EMPTY_LINE }]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entry?.id, entry?.lines]);

  // Sprint 6.9.1 (item D, decision 6): a legal entity that started
  // activity inside the system (no prior balances to open) still needs
  // a written attestation to approve — suggest the standard wording
  // instead of leaving the accountant to invent one from scratch.
  useEffect(() => {
    if (entry && entry.status === "pending_approval" && entry.lines.length === 0 && !attestation) {
      setAttestation(t("noOpeningLinesAttestationSuggestion"));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entry?.id, entry?.status]);

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

  const saveLines = async () => {
    setError(null);
    try {
      const updated = await api.patch<OpeningBalanceEntry>(`/opening-balances/${id}/lines/`, {
        lines: linesToPayload(editLines),
      });
      setEntry(updated);
    } catch (err) {
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const deleteEntry = async () => {
    if (!window.confirm(t("deleteOpeningBalanceConfirm"))) return;
    try {
      await api.delete(`/opening-balances/${id}/`);
      router.push("/dashboard/accounting/opening-balances");
    } catch (err) {
      window.alert(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const debitTotal = entry.lines.reduce((sum, l) => sum + parseFloat(l.debit_base), 0);
  const creditTotal = entry.lines.reduce((sum, l) => sum + parseFloat(l.credit_base), 0);
  const editDebitTotal = editLines.reduce((sum, l) => sum + (parseFloat(l.debitFc) || 0), 0);
  const editCreditTotal = editLines.reduce((sum, l) => sum + (parseFloat(l.creditFc) || 0), 0);

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

      {entry.status === "draft" ? (
        <div className="card">
          <h3>{t("editLines")}</h3>
          <OpeningBalanceLinesEditor
            lines={editLines}
            onChange={setEditLines}
            accounts={accounts}
            parties={parties}
            costCenters={costCenters}
            showCostCenterUI={showCostCenterUI}
          />
          <p>
            {t("difference")}: <Money amount={String(editDebitTotal - editCreditTotal)} /> (
            {t("balanced")}: {editDebitTotal === editCreditTotal ? "✓" : "✗"})
          </p>
          <button className="primary" type="button" onClick={saveLines}>{t("saveLines")}</button>
        </div>
      ) : (
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
      )}

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

      <WarningsBanner warnings={error ? [error] : []} variant="error" />

      {entry.status === "draft" && (
        <div className="card">
          <button className="primary" onClick={() => runAction("submit")}>{t("submitForApproval")}</button>
          <button className="secondary" style={{ marginInlineStart: "0.5rem" }} onClick={deleteEntry}>
            {t("deleteOpeningBalance")}
          </button>
        </div>
      )}

      {entry.status === "rejected" && (
        <div className="card">
          <button className="secondary" onClick={deleteEntry}>{t("deleteOpeningBalance")}</button>
        </div>
      )}

      {entry.status === "pending_approval" && (
        <div className="card">
          <FormField name="attestation_text" label={t("attestationText")} style={{ maxWidth: "480px" }}>
            <textarea value={attestation} onChange={(e) => setAttestation(e.target.value)} rows={3} />
          </FormField>
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
              <FormField name="reason" style={{ display: "inline-block", maxWidth: "300px" }}>
                <input
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  placeholder={t("reason")}
                  style={{ minWidth: "260px" }}
                />
              </FormField>
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
