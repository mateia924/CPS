"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, fieldErrors, generalError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { StatusBadge } from "@/components/StatusBadge";
import { AttachmentPanel } from "@/components/AttachmentPanel";
import { FormField } from "@/components/FormField";
import { WarningsBanner } from "@/components/WarningsBanner";
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
  // Sprint 6.5.18 (UAT item 5): the LIST's own optional entity filter,
  // separate from `legalEntityId` above (the new-entry form's field).
  const [listEntityId, setListEntityId] = useState("");
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [currency, setCurrency] = useState("");
  const [exchangeRate, setExchangeRate] = useState("");
  const [memo, setMemo] = useState("");
  const [reference, setReference] = useState("");
  const [overrideReason, setOverrideReason] = useState("");
  const [lines, setLines] = useState<LineDraft[]>([{ ...EMPTY_LINE }, { ...EMPTY_LINE }]);
  const [error, setError] = useState<string | null>(null);
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});
  const [refreshToken, setRefreshToken] = useState(0);
  const [showFx, setShowFx] = useState(false);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [reasonFor, setReasonFor] = useState<{ id: string; kind: "reject" | "reverse" } | null>(null);
  const [attachmentsFor, setAttachmentsFor] = useState<string | null>(null);
  const [reasonText, setReasonText] = useState("");
  const [reverseDate, setReverseDate] = useState("");

  const showCostCenterUI = !!me && me.features.cost_centers;

  useEffect(() => {
    (async () => {
      const [entityData, tree] = await Promise.all([
        api.get<Paginated<LegalEntity>>("/legal-entities/"),
        api.get<AccountTreeNode[]>("/accounts/tree/"),
      ]);
      setEntities(entityData.results.filter((entity) => entity.entity_type !== "holding"));
      // Sprint 6.0.1-B item 6: default to the user's own primary branch.
      if (me?.default_legal_entity_id) setLegalEntityId((prev) => prev || me.default_legal_entity_id!);
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
    setOverrideReason("");
    setLines([{ ...EMPTY_LINE }, { ...EMPTY_LINE }]);
    setShowFx(false);
    setError(null);
    setFieldErr({});
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setFieldErr({});
    const payload = {
      legal_entity: legalEntityId,
      date,
      ...(currency ? { currency } : {}),
      ...(exchangeRate ? { exchange_rate: exchangeRate } : {}),
      memo,
      reference,
      ...(overrideReason ? { override_reason: overrideReason } : {}),
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
      const created = await api.post<JournalEntry>("/journal-entries/", payload);
      setWarnings(created.warnings || []);
      resetForm();
      setRefreshToken((n) => n + 1);
    } catch (err) {
      setFieldErr(fieldErrors((err as { body?: unknown }).body));
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const runTransition = async (entry: JournalEntry, action: string, reload: () => void) => {
    await api.post(`/journal-entries/${entry.id}/${action}/`);
    reload();
  };

  const submitReason = async (reload: () => void) => {
    if (!reasonFor) return;
    const result = await api.post<JournalEntry>(`/journal-entries/${reasonFor.id}/${reasonFor.kind}/`, {
      reason: reasonText,
      ...(reasonFor.kind === "reverse" && reverseDate ? { date: reverseDate } : {}),
    });
    setWarnings(result.warnings || []);
    setReasonFor(null);
    setReasonText("");
    setReverseDate("");
    reload();
  };

  return (
    <div>
      <h1>{t("manualJournalEntries")}</h1>
      <WarningsBanner warnings={warnings} />

      <div className="card">
        <h3>{t("createJournalEntry")}</h3>
        <form onSubmit={onSubmit}>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <FormField name="date" label={t("date")} required error={fieldErr.date}>
              <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
            </FormField>
            <FormField name="memo" style={{ flex: 1, minWidth: "220px" }} error={fieldErr.memo}>
              <input value={memo} onChange={(e) => setMemo(e.target.value)} />
            </FormField>
          </div>

          <details style={{ marginTop: "0.75rem" }}>
            <summary style={{ cursor: "pointer" }}>{t("advanced")}</summary>
            <FormField
              name="legal_entity" label={t("legalEntity")} required error={fieldErr.legal_entity}
              style={{ marginTop: "0.75rem", maxWidth: "320px" }}
            >
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
            </FormField>
          </details>

          {!showFx ? (
            <button type="button" className="secondary" onClick={() => setShowFx(true)} style={{ marginBottom: "0.75rem" }}>
              {t("foldCurrencyFx")}
            </button>
          ) : (
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginBottom: "0.75rem" }}>
              <FormField name="currency" error={fieldErr.currency}>
                <input value={currency} onChange={(e) => setCurrency(e.target.value)} maxLength={3} />
              </FormField>
              <FormField name="exchange_rate" label={t("exchangeRateLabel")} error={fieldErr.exchange_rate}>
                <input value={exchangeRate} onChange={(e) => setExchangeRate(e.target.value)} />
              </FormField>
              <FormField name="reference" error={fieldErr.reference}>
                <input value={reference} onChange={(e) => setReference(e.target.value)} />
              </FormField>
              <FormField
                name="override_reason" label={t("overrideReason")} error={fieldErr.override_reason}
                style={{ flex: 1, minWidth: "220px" }}
              >
                <input
                  value={overrideReason}
                  onChange={(e) => setOverrideReason(e.target.value)}
                  placeholder={t("overridePosting")}
                />
              </FormField>
            </div>
          )}

          {lines.map((line, i) => (
            <div key={i} style={{ display: "flex", gap: "0.75rem", alignItems: "end", flexWrap: "wrap" }}>
              <FormField name="account" style={{ flex: 1, minWidth: "220px" }}>
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
              </FormField>
              {showCostCenterUI && (
                <FormField name="cost_center" style={{ minWidth: "160px" }}>
                  <select value={line.costCenter} onChange={(e) => updateLine(i, "costCenter", e.target.value)}>
                    <option value="">{t("none")}</option>
                    {costCenters.map((cc) => (
                      <option key={cc.id} value={cc.id}>
                        {cc.code} — {cc.name}
                      </option>
                    ))}
                  </select>
                </FormField>
              )}
              <FormField name="debit_fc" style={{ width: "130px" }}>
                <input
                  type="number"
                  step="0.01"
                  value={line.debitFc}
                  onChange={(e) => updateLine(i, "debitFc", e.target.value)}
                />
              </FormField>
              <FormField name="credit_fc" style={{ width: "130px" }}>
                <input
                  type="number"
                  step="0.01"
                  value={line.creditFc}
                  onChange={(e) => updateLine(i, "creditFc", e.target.value)}
                />
              </FormField>
            </div>
          ))}

          <button type="button" className="secondary" onClick={addLine} style={{ marginBottom: "1rem" }}>
            {t("addManualLine")}
          </button>
          <br />
          <WarningsBanner warnings={error ? [error] : []} variant="error" />
          <button className="primary" type="submit">
            {t("createJournalEntry")}
          </button>
        </form>
      </div>

      {reasonFor && (
        <div className="card">
          <h3>{reasonFor.kind === "reject" ? t("rejectReason") : t("reverseReason")}</h3>
          <FormField name="reason" required style={{ maxWidth: "320px" }}>
            <input value={reasonText} onChange={(e) => setReasonText(e.target.value)} style={{ minWidth: "300px" }} />
          </FormField>
          {reasonFor.kind === "reverse" && (
            <FormField name="date" label={t("reverseDate")} style={{ marginTop: "0.5rem", maxWidth: "200px" }}>
              <input type="date" value={reverseDate} onChange={(e) => setReverseDate(e.target.value)} />
            </FormField>
          )}
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
                setReverseDate("");
              }}
            >
              {t("cancel")}
            </button>
          </div>
        </div>
      )}

      <FormField name="list_entity_filter" label={t("entityFilter")}>
        <select value={listEntityId} onChange={(e) => setListEntityId(e.target.value)}>
          <option value="">{t("allEntities")}</option>
          {entities.map((entity) => (
            <option key={entity.id} value={entity.id}>{entity.code} — {entity.name}</option>
          ))}
        </select>
      </FormField>

      <DataTable<JournalEntry>
        endpoint="/journal-entries/"
        extraParams={{ legal_entity: listEntityId }}
        refreshToken={refreshToken}
        hasActiveToggle={false}
        columns={[
          {
            key: "number", label: t("number"), sortable: true,
            // Sprint 6.5.18 (UAT item 9): the entry's own number is
            // now a direct link to its details page, not plain text.
            render: (row) => <Link href={`/dashboard/accounting/journal-entries/${row.id}`}>{row.number}</Link>,
          },
          { key: "legal_entity_name", label: t("legalEntity") },
          { key: "date", label: t("date"), sortable: true },
          { key: "memo", label: t("memo") },
          { key: "status", label: t("status"), render: (row) => <StatusBadge status={row.status} /> },
        ]}
        renderExtraActions={(entry, reload) => (
          <>
            {entry.status === "draft" && !entry.produced_by && (
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
                <button
                  className="secondary"
                  style={{ marginInlineStart: "0.4rem" }}
                  onClick={() => runTransition(entry, "withdraw", reload)}
                >
                  {t("withdraw")}
                </button>
              </>
            )}
            {entry.status === "approved" && (
              <button className="secondary" onClick={() => runTransition(entry, "post", reload)}>
                {t("post")}
              </button>
            )}
            {entry.status === "posted" && !entry.produced_by && (
              <button className="secondary" onClick={() => setReasonFor({ id: entry.id, kind: "reverse" })}>
                {t("reverse")}
              </button>
            )}
            <button
              className="secondary"
              style={{ marginInlineStart: "0.4rem" }}
              onClick={() => setAttachmentsFor(attachmentsFor === entry.id ? null : entry.id)}
            >
              📎 {t("attachments")}
            </button>
          </>
        )}
      />

      {attachmentsFor && <AttachmentPanel targetType="journal_entry" targetId={attachmentsFor} />}
    </div>
  );
}
