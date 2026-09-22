"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { StatusBadge } from "@/components/StatusBadge";
import { flattenLeafAccounts, type FlatAccountOption } from "@/lib/accounts";
import type { AccountTreeNode, CostCenter, JournalEntry, LegalEntity, Paginated } from "@/lib/types";

interface LineDraft {
  account: string;
  costCenter: string;
  description: string;
  debitFc: string;
  creditFc: string;
}

const EMPTY_LINE: LineDraft = { account: "", costCenter: "", description: "", debitFc: "", creditFc: "" };

export default function JournalEntriesPage() {
  const { t } = useLocale();
  const { me } = useAuth();
  const [entities, setEntities] = useState<LegalEntity[]>([]);
  const [accounts, setAccounts] = useState<FlatAccountOption[]>([]);
  const [costCenters, setCostCenters] = useState<CostCenter[]>([]);
  const [legalEntityId, setLegalEntityId] = useState("");
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [currency, setCurrency] = useState("");
  const [exchangeRate, setExchangeRate] = useState("");
  const [memo, setMemo] = useState("");
  const [reference, setReference] = useState("");
  const [lines, setLines] = useState<LineDraft[]>([{ ...EMPTY_LINE }, { ...EMPTY_LINE }]);
  const [error, setError] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [showFx, setShowFx] = useState(false);
  const [reasonFor, setReasonFor] = useState<{ id: string; kind: "reject" | "reverse" } | null>(null);
  const [reasonText, setReasonText] = useState("");

  const showCostCenterUI = !!me && me.features.cost_centers;

  useEffect(() => {
    (async () => {
      const [entityData, tree] = await Promise.all([
        api.get<Paginated<LegalEntity>>("/legal-entities/"),
        api.get<AccountTreeNode[]>("/accounts/tree/"),
      ]);
      setEntities(entityData.results.filter((entity) => entity.entity_type !== "holding"));
      setAccounts(flattenLeafAccounts(tree));
      if (showCostCenterUI) {
        const ccData = await api.get<Paginated<CostCenter>>("/cost-centers/");
        setCostCenters(ccData.results);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showCostCenterUI]);

  const addLine = () => setLines([...lines, { ...EMPTY_LINE }]);
  const updateLine = (index: number, field: keyof LineDraft, value: string) => {
    setLines(lines.map((line, i) => (i === index ? { ...line, [field]: value } : line)));
  };

  const resetForm = () => {
    setLegalEntityId("");
    setDate(new Date().toISOString().slice(0, 10));
    setCurrency("");
    setExchangeRate("");
    setMemo("");
    setReference("");
    setLines([{ ...EMPTY_LINE }, { ...EMPTY_LINE }]);
    setShowFx(false);
    setError(null);
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const payload = {
      legal_entity: legalEntityId,
      date,
      ...(currency ? { currency } : {}),
      ...(exchangeRate ? { exchange_rate: exchangeRate } : {}),
      memo,
      reference,
      lines: lines
        .filter((l) => l.account && (l.debitFc || l.creditFc))
        .map((l) => ({
          account: l.account,
          ...(l.costCenter ? { cost_center: l.costCenter } : {}),
          description: l.description,
          debit_fc: l.debitFc || "0",
          credit_fc: l.creditFc || "0",
        })),
    };
    try {
      await api.post("/journal-entries/", payload);
      resetForm();
      setRefreshToken((n) => n + 1);
    } catch {
      setError("Could not save this journal entry.");
    }
  };

  const runTransition = async (entry: JournalEntry, action: string, reload: () => void) => {
    await api.post(`/journal-entries/${entry.id}/${action}/`);
    reload();
  };

  const submitReason = async (reload: () => void) => {
    if (!reasonFor) return;
    await api.post(`/journal-entries/${reasonFor.id}/${reasonFor.kind}/`, { reason: reasonText });
    setReasonFor(null);
    setReasonText("");
    reload();
  };

  return (
    <div>
      <h1>{t("manualJournalEntries")}</h1>

      <div className="card">
        <h3>{t("createJournalEntry")}</h3>
        <form onSubmit={onSubmit}>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <div className="form-field">
              <label>{t("legalEntity")}</label>
              <select value={legalEntityId} onChange={(e) => setLegalEntityId(e.target.value)} required>
                <option value="" disabled>
                  —
                </option>
                {entities.map((entity) => (
                  <option key={entity.id} value={entity.id}>
                    {entity.code} — {entity.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-field">
              <label>{t("date")}</label>
              <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
            </div>
            <div className="form-field" style={{ flex: 1, minWidth: "220px" }}>
              <label>{t("memo")}</label>
              <input value={memo} onChange={(e) => setMemo(e.target.value)} />
            </div>
          </div>

          {!showFx ? (
            <button type="button" className="secondary" onClick={() => setShowFx(true)} style={{ marginBottom: "0.75rem" }}>
              {t("foldCurrencyFx")}
            </button>
          ) : (
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginBottom: "0.75rem" }}>
              <div className="form-field">
                <label>{t("currency")}</label>
                <input value={currency} onChange={(e) => setCurrency(e.target.value)} maxLength={3} />
              </div>
              <div className="form-field">
                <label>{t("exchangeRateLabel")}</label>
                <input value={exchangeRate} onChange={(e) => setExchangeRate(e.target.value)} />
              </div>
              <div className="form-field">
                <label>{t("reference")}</label>
                <input value={reference} onChange={(e) => setReference(e.target.value)} />
              </div>
            </div>
          )}

          {lines.map((line, i) => (
            <div key={i} style={{ display: "flex", gap: "0.75rem", alignItems: "end", flexWrap: "wrap" }}>
              <div className="form-field" style={{ flex: 1, minWidth: "220px" }}>
                <label>{t("account")}</label>
                <select value={line.account} onChange={(e) => updateLine(i, "account", e.target.value)} required>
                  <option value="" disabled>
                    —
                  </option>
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.label}
                    </option>
                  ))}
                </select>
              </div>
              {showCostCenterUI && (
                <div className="form-field" style={{ minWidth: "160px" }}>
                  <label>{t("costCenter")}</label>
                  <select value={line.costCenter} onChange={(e) => updateLine(i, "costCenter", e.target.value)}>
                    <option value="">{t("none")}</option>
                    {costCenters.map((cc) => (
                      <option key={cc.id} value={cc.id}>
                        {cc.code} — {cc.name}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              <div className="form-field" style={{ width: "130px" }}>
                <label>{t("debitFc")}</label>
                <input
                  type="number"
                  step="0.01"
                  value={line.debitFc}
                  onChange={(e) => updateLine(i, "debitFc", e.target.value)}
                />
              </div>
              <div className="form-field" style={{ width: "130px" }}>
                <label>{t("creditFc")}</label>
                <input
                  type="number"
                  step="0.01"
                  value={line.creditFc}
                  onChange={(e) => updateLine(i, "creditFc", e.target.value)}
                />
              </div>
            </div>
          ))}

          <button type="button" className="secondary" onClick={addLine} style={{ marginBottom: "1rem" }}>
            {t("addManualLine")}
          </button>
          <br />
          {error && <p className="error-text">{error}</p>}
          <button className="primary" type="submit">
            {t("createJournalEntry")}
          </button>
        </form>
      </div>

      {reasonFor && (
        <div className="card">
          <h3>{reasonFor.kind === "reject" ? t("rejectReason") : t("reverseReason")}</h3>
          <input value={reasonText} onChange={(e) => setReasonText(e.target.value)} style={{ minWidth: "300px" }} />
          <div style={{ marginTop: "0.75rem" }}>
            <button className="primary" onClick={() => submitReason(() => setRefreshToken((n) => n + 1))}>
              {t("save")}
            </button>
            <button
              type="button"
              className="secondary"
              style={{ marginInlineStart: "0.5rem" }}
              onClick={() => {
                setReasonFor(null);
                setReasonText("");
              }}
            >
              {t("cancel")}
            </button>
          </div>
        </div>
      )}

      <DataTable<JournalEntry>
        endpoint="/journal-entries/"
        refreshToken={refreshToken}
        hasActiveToggle={false}
        columns={[
          { key: "number", label: t("number"), sortable: true },
          { key: "legal_entity_name", label: t("legalEntity") },
          { key: "date", label: t("date"), sortable: true },
          { key: "memo", label: t("memo") },
          { key: "status", label: t("status"), render: (row) => <StatusBadge status={row.status} /> },
        ]}
        renderExtraActions={(entry, reload) => (
          <>
            {entry.status === "draft" && !entry.source_type && (
              <button className="secondary" onClick={() => runTransition(entry, "submit", reload)}>
                {t("submitForApproval")}
              </button>
            )}
            {entry.status === "pending_approval" && (
              <>
                <button
                  className="secondary"
                  style={{ marginInlineStart: "0.4rem" }}
                  onClick={() => runTransition(entry, "approve", reload)}
                >
                  {t("approve")}
                </button>
                <button
                  className="secondary"
                  style={{ marginInlineStart: "0.4rem" }}
                  onClick={() => setReasonFor({ id: entry.id, kind: "reject" })}
                >
                  {t("reject")}
                </button>
              </>
            )}
            {entry.status === "approved" && (
              <button className="secondary" onClick={() => runTransition(entry, "post", reload)}>
                {t("post")}
              </button>
            )}
            {entry.status === "posted" && !entry.source_type && (
              <button className="secondary" onClick={() => setReasonFor({ id: entry.id, kind: "reverse" })}>
                {t("reverse")}
              </button>
            )}
          </>
        )}
      />
    </div>
  );
}
