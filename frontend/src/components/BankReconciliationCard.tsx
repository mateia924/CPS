"use client";

import { useEffect, useState } from "react";
import { api, ApiError, generalError } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import type {
  BankStatement,
  BankStatementLine,
  Paginated,
  ReconciliationReport,
  StatementLineCandidate,
} from "@/lib/types";

/** Sprint 5.5 (blocks 5.5.1-5.5.3): "التسوية" tab on the bank detail
 * screen — import a statement, review/match its lines, and read the
 * auditor-form reconciliation report. One component (not split across
 * three) since the three pieces share the same selected-statement
 * state. */
export function BankReconciliationCard({ bankId }: { bankId: string }) {
  const { t } = useLocale();
  const [statements, setStatements] = useState<BankStatement[]>([]);
  const [selected, setSelected] = useState<BankStatement | null>(null);
  const [report, setReport] = useState<ReconciliationReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showImport, setShowImport] = useState(false);

  const loadStatements = () => {
    api
      .get<Paginated<BankStatement> | BankStatement[]>(`/bank-statements/?bank=${bankId}`)
      .then((data) => setStatements(Array.isArray(data) ? data : data.results));
  };

  const loadReport = () => {
    api.get<ReconciliationReport>(`/banks/${bankId}/reconciliation-report/`).then(setReport);
  };

  useEffect(() => {
    loadStatements();
    loadReport();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bankId]);

  const openStatement = async (id: string) => {
    const full = await api.get<BankStatement>(`/bank-statements/${id}/`);
    setSelected(full);
  };

  const refreshSelected = async () => {
    if (!selected) return;
    const full = await api.get<BankStatement>(`/bank-statements/${selected.id}/`);
    setSelected(full);
    loadStatements();
    loadReport();
  };

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3>{t("reconciliationTab")}</h3>
        <button className="secondary" onClick={() => setShowImport((v) => !v)}>
          {t("importStatement")}
        </button>
      </div>

      {error && <p style={{ color: "#a3492f" }}>{error}</p>}

      {showImport && (
        <ImportStatementForm
          bankId={bankId}
          onDone={() => {
            setShowImport(false);
            loadStatements();
            loadReport();
          }}
          onError={setError}
        />
      )}

      {report && (
        <div style={{ marginTop: "1rem" }}>
          <h4>{t("reconciliationReport")}</h4>
          <p>
            {t("bankAdjustedBalance")}: {report.bank_adjusted_balance} {report.currency} —{" "}
            {t("bookAdjustedBalance")}: {report.book_adjusted_balance} {report.currency}
          </p>
          <p style={{ fontWeight: 600, color: report.difference === "0.00" || Number(report.difference) === 0 ? "#1f9d55" : "#a3492f" }}>
            {t("difference")}: {report.difference} {report.currency} —{" "}
            {Number(report.difference) === 0 ? t("reconciled") : t("notReconciled")}
          </p>
          <p>
            {t("reconciledRatio")}: {(report.reconciled_ratio * 100).toFixed(1)}%
          </p>
        </div>
      )}

      <div style={{ marginTop: "1rem" }}>
        <h4>{t("statementsList")}</h4>
        <table>
          <thead>
            <tr>
              <th>{t("periodStart")}</th>
              <th>{t("periodEnd")}</th>
              <th>{t("lineCount")}</th>
              <th>{t("reconciledRatio")}</th>
            </tr>
          </thead>
          <tbody>
            {statements.map((s) => (
              <tr key={s.id} style={{ cursor: "pointer" }} onClick={() => openStatement(s.id)}>
                <td>{s.period_start}</td>
                <td>{s.period_end}</td>
                <td>{s.line_count}</td>
                <td>{(s.reconciled_ratio * 100).toFixed(0)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selected && (
        <StatementLinesPanel statement={selected} onChanged={refreshSelected} />
      )}
    </div>
  );
}

function ImportStatementForm({
  bankId,
  onDone,
  onError,
}: {
  bankId: string;
  onDone: () => void;
  onError: (message: string | null) => void;
}) {
  const { t } = useLocale();
  const [format, setFormat] = useState<"csv" | "xlsx" | "mt940">("csv");
  const [file, setFile] = useState<File | null>(null);
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [opening, setOpening] = useState("0.00");
  const [closing, setClosing] = useState("0.00");
  const [dateCol, setDateCol] = useState("Date");
  const [amountCol, setAmountCol] = useState("Amount");
  const [descCol, setDescCol] = useState("Description");
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    if (!file) return;
    setSubmitting(true);
    onError(null);
    const formData = new FormData();
    formData.append("bank", bankId);
    formData.append("file", file);
    formData.append("format", format);
    formData.append("period_start", periodStart);
    formData.append("period_end", periodEnd);
    formData.append("opening_balance", opening);
    formData.append("closing_balance", closing);
    if (format !== "mt940") {
      formData.append(
        "column_mapping",
        JSON.stringify({ date: dateCol, amount: amountCol, description: descCol })
      );
    }
    try {
      await api.upload(`/bank-statements/import/`, formData);
      onDone();
    } catch (e) {
      onError(generalError(e instanceof ApiError ? e.body : null, t("couldNotSave")));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="card" style={{ background: "var(--surface-2)" }}>
      <label>
        {t("statementFormat")}
        <select value={format} onChange={(e) => setFormat(e.target.value as typeof format)}>
          <option value="csv">CSV</option>
          <option value="xlsx">Excel</option>
          <option value="mt940">MT940</option>
        </select>
      </label>
      <label>
        {t("statementFile")}
        <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </label>
      <label>
        {t("periodStart")}
        <input type="date" value={periodStart} onChange={(e) => setPeriodStart(e.target.value)} />
      </label>
      <label>
        {t("periodEnd")}
        <input type="date" value={periodEnd} onChange={(e) => setPeriodEnd(e.target.value)} />
      </label>
      <label>
        {t("openingBalance")}
        <input value={opening} onChange={(e) => setOpening(e.target.value)} />
      </label>
      <label>
        {t("closingBalance")}
        <input value={closing} onChange={(e) => setClosing(e.target.value)} />
      </label>
      {format !== "mt940" && (
        <>
          <label>
            {t("dateColumn")}
            <input value={dateCol} onChange={(e) => setDateCol(e.target.value)} />
          </label>
          <label>
            {t("amountColumn")}
            <input value={amountCol} onChange={(e) => setAmountCol(e.target.value)} />
          </label>
          <label>
            {t("descriptionColumn")}
            <input value={descCol} onChange={(e) => setDescCol(e.target.value)} />
          </label>
        </>
      )}
      <button className="primary" disabled={submitting || !file} onClick={submit} style={{ marginTop: "0.5rem" }}>
        {t("importStatement")}
      </button>
    </div>
  );
}

function StatementLinesPanel({
  statement,
  onChanged,
}: {
  statement: BankStatement;
  onChanged: () => void;
}) {
  const { t } = useLocale();
  const [candidatesFor, setCandidatesFor] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<StatementLineCandidate[]>([]);
  const [selectedCandidates, setSelectedCandidates] = useState<string[]>([]);

  const openCandidates = async (lineId: string) => {
    const list = await api.get<StatementLineCandidate[]>(`/statement-lines/${lineId}/candidates/`);
    setCandidates(list);
    setSelectedCandidates([]);
    setCandidatesFor(lineId);
  };

  const match = async (lineId: string) => {
    await api.post(`/statement-lines/${lineId}/match/`, { journal_line_ids: selectedCandidates });
    setCandidatesFor(null);
    onChanged();
  };

  const unmatch = async (lineId: string) => {
    await api.post(`/statement-lines/${lineId}/unmatch/`, {});
    onChanged();
  };

  const ignore = async (lineId: string) => {
    const reason = window.prompt(t("ignoreReason"));
    if (!reason) return;
    await api.post(`/statement-lines/${lineId}/ignore/`, { reason });
    onChanged();
  };

  return (
    <div style={{ marginTop: "1rem" }}>
      <h4>{t("statementLines")}</h4>
      <table>
        <thead>
          <tr>
            <th>{t("date")}</th>
            <th>{t("description")}</th>
            <th>{t("amount")}</th>
            <th>{t("status")}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {(statement.lines ?? []).map((line: BankStatementLine) => (
            <>
              <tr key={line.id}>
                <td>{line.date}</td>
                <td>{line.description}</td>
                <td>{line.amount}</td>
                <td>{line.status} {line.matched_by ? `(${line.matched_by})` : ""}</td>
                <td>
                  {line.status === "unmatched" && (
                    <>
                      <button className="secondary" onClick={() => openCandidates(line.id)}>
                        {t("matchSelected")}
                      </button>{" "}
                      <button className="secondary" onClick={() => ignore(line.id)}>
                        {t("ignoreLine")}
                      </button>
                    </>
                  )}
                  {line.status === "matched" && (
                    <button className="secondary" onClick={() => unmatch(line.id)}>
                      {t("unmatch")}
                    </button>
                  )}
                </td>
              </tr>
              {candidatesFor === line.id && (
                <tr>
                  <td colSpan={5}>
                    <ul>
                      {candidates.map((c) => (
                        <li key={c.id}>
                          <label>
                            <input
                              type="checkbox"
                              checked={selectedCandidates.includes(c.id)}
                              onChange={(e) =>
                                setSelectedCandidates((prev) =>
                                  e.target.checked ? [...prev, c.id] : prev.filter((id) => id !== c.id)
                                )
                              }
                            />
                            {c.date} — {c.entry_number} — {c.description} — {c.debit_fc}/{c.credit_fc}
                          </label>
                        </li>
                      ))}
                      {candidates.length === 0 && <li>{t("noData")}</li>}
                    </ul>
                    <button className="primary" disabled={!selectedCandidates.length} onClick={() => match(line.id)}>
                      {t("matchSelected")}
                    </button>
                  </td>
                </tr>
              )}
            </>
          ))}
        </tbody>
      </table>
    </div>
  );
}
