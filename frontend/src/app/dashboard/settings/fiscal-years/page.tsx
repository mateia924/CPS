"use client";

import { useEffect, useState } from "react";
import { api, fieldErrors, generalError } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { FormField } from "@/components/FormField";
import { WarningsBanner } from "@/components/WarningsBanner";
import type { FiscalPeriod, FiscalPeriodicStatus, FiscalYear, Paginated, PeriodChecklistItem } from "@/lib/types";

const STATUS_LABEL_KEY: Record<FiscalPeriodicStatus, string> = {
  open: "periodOpen",
  closed: "periodClosed",
  locked: "periodLocked",
};

const LEVEL_COLOR: Record<PeriodChecklistItem["level"], string> = {
  block: "var(--status-void)",
  warn: "var(--status-pending)",
  info: "var(--muted)",
};

// Sprint 6.1 (3.9): الإعدادات ← "السنوات والفترات المالية" — جدول
// السنوات، فترات كل سنة بحالتها، أزرار حسب الحالة، إنشاء سنة بمعالج
// طول الفترة.
export default function FiscalYearsPage() {
  const { t } = useLocale();
  const [years, setYears] = useState<FiscalYear[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [periodLength, setPeriodLength] = useState<"monthly" | "quarterly" | "custom">("monthly");
  const [customDates, setCustomDates] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});
  const [actionError, setActionError] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [checklistFor, setChecklistFor] = useState<FiscalPeriod | null>(null);
  const [checklistItems, setChecklistItems] = useState<PeriodChecklistItem[] | null>(null);
  const [acknowledgeWarnings, setAcknowledgeWarnings] = useState(false);
  const [closeNote, setCloseNote] = useState("");

  const load = () => {
    api.get<Paginated<FiscalYear>>("/fiscal-years/").then((data) => setYears(data.results));
  };

  useEffect(load, [refreshToken]);

  const submitCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setFieldErr({});
    try {
      await api.post("/fiscal-years/", {
        name,
        start_date: startDate,
        end_date: endDate,
        period_length: periodLength,
        ...(periodLength === "custom"
          ? { custom_period_end_dates: customDates.split(",").map((d) => d.trim()).filter(Boolean) }
          : {}),
      });
      setShowCreate(false);
      setName("");
      setStartDate("");
      setEndDate("");
      setCustomDates("");
      setRefreshToken((n) => n + 1);
    } catch (err) {
      setFieldErr(fieldErrors((err as { body?: unknown }).body));
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const runPeriodAction = async (period: FiscalPeriod, action: "close" | "reopen" | "lock", payload: Record<string, unknown>) => {
    setActionError(null);
    try {
      await api.post(`/fiscal-periods/${period.id}/${action}/`, payload);
      setRefreshToken((n) => n + 1);
    } catch (err) {
      setActionError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const openChecklist = async (period: FiscalPeriod) => {
    setChecklistFor(period);
    setAcknowledgeWarnings(false);
    setCloseNote("");
    const data = await api.get<{ items: PeriodChecklistItem[] }>(`/fiscal-periods/${period.id}/checklist/`);
    setChecklistItems(data.items);
  };

  const closePeriod = async () => {
    if (!checklistFor) return;
    await runPeriodAction(checklistFor, "close", { note: closeNote, acknowledge_warnings: acknowledgeWarnings });
    setChecklistFor(null);
    setChecklistItems(null);
  };

  const reopenPeriod = (period: FiscalPeriod) => {
    const reason = window.prompt(t("reopenReason"));
    if (!reason) return;
    runPeriodAction(period, "reopen", { reason });
  };

  const lockPeriod = (period: FiscalPeriod) => {
    const lock_attestation = window.prompt(t("lockAttestation"));
    if (!lock_attestation) return;
    runPeriodAction(period, "lock", { lock_attestation });
  };

  return (
    <div>
      <h1>{t("fiscalYearsNav")}</h1>

      <div className="card">
        <button className="secondary" onClick={() => setShowCreate((v) => !v)}>
          {t("createFiscalYear")}
        </button>
        {showCreate && (
          <form onSubmit={submitCreate} style={{ marginTop: "1rem" }}>
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
              <FormField name="name" label={t("fiscalYearName")} required error={fieldErr.name}>
                <input value={name} onChange={(e) => setName(e.target.value)} required />
              </FormField>
              <FormField name="start_date" label={t("periodStart")} required error={fieldErr.start_date}>
                <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} required />
              </FormField>
              <FormField name="end_date" label={t("periodEnd")} required error={fieldErr.end_date}>
                <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} required />
              </FormField>
              <FormField name="period_length" label={t("periodLength")} error={fieldErr.period_length}>
                <select value={periodLength} onChange={(e) => setPeriodLength(e.target.value as typeof periodLength)}>
                  <option value="monthly">{t("monthly")}</option>
                  <option value="quarterly">{t("quarterly")}</option>
                  <option value="custom">{t("custom")}</option>
                </select>
              </FormField>
              {periodLength === "custom" && (
                <FormField
                  name="custom_period_end_dates" label={`${t("custom")} — end dates (YYYY-MM-DD, comma-separated)`}
                  error={fieldErr.custom_period_end_dates} style={{ flex: 1, minWidth: "260px" }}
                >
                  <input value={customDates} onChange={(e) => setCustomDates(e.target.value)} />
                </FormField>
              )}
            </div>
            <WarningsBanner warnings={error ? [error] : []} variant="error" />
            <button className="primary" type="submit" style={{ marginTop: "0.5rem" }}>
              {t("save")}
            </button>
          </form>
        )}
      </div>

      <WarningsBanner warnings={actionError ? [actionError] : []} variant="error" />

      {years.map((year) => (
        <div key={year.id} className="card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <strong>{year.name}</strong> ({year.start_date} — {year.end_date}) —{" "}
              {t(STATUS_LABEL_KEY[year.status])}
              {year.is_auto_created && (
                <span style={{ marginInlineStart: "0.5rem", color: "var(--muted)", fontSize: "0.8rem" }}>
                  ({t("autoCreated")})
                </span>
              )}
            </div>
            <button className="secondary" onClick={() => setExpanded((cur) => (cur === year.id ? null : year.id))}>
              {expanded === year.id ? "−" : "+"}
            </button>
          </div>

          {expanded === year.id && (
            <table style={{ marginTop: "0.75rem" }}>
              <thead>
                <tr>
                  <th>#</th>
                  <th>{t("periodStart")}</th>
                  <th>{t("periodEnd")}</th>
                  <th>{t("status")}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {year.periods.map((period) => (
                  <tr key={period.id}>
                    <td>{period.seq}</td>
                    <td>{period.start_date}</td>
                    <td>{period.end_date}</td>
                    <td>{t(STATUS_LABEL_KEY[period.status])}</td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      {period.status === "open" && (
                        <button className="secondary" onClick={() => openChecklist(period)}>
                          {t("closeChecklist")}
                        </button>
                      )}
                      {period.status === "closed" && (
                        <>
                          <button className="secondary" onClick={() => reopenPeriod(period)}>
                            {t("reopenPeriod")}
                          </button>{" "}
                          <button className="secondary" onClick={() => lockPeriod(period)}>
                            {t("lockPeriod")}
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ))}

      {checklistFor && (
        <div className="card">
          <h3>
            {t("closeChecklist")} — #{checklistFor.seq} ({checklistFor.start_date} — {checklistFor.end_date})
          </h3>
          {checklistItems === null ? (
            <p>…</p>
          ) : (
            <>
              <ul>
                {checklistItems.map((item, i) => (
                  <li key={i} style={{ color: LEVEL_COLOR[item.level] }}>
                    [{item.level.toUpperCase()}] {item.message}
                    {item.references && item.references.length > 0 && (
                      <ul>
                        {item.references.map((ref) => (
                          <li key={ref.id}>{ref.reference}</li>
                        ))}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>

              {checklistItems.some((item) => item.level === "block") ? (
                <p className="error-text">{t("couldNotSave")}</p>
              ) : (
                <>
                  {checklistItems.some((item) => item.level === "warn") && (
                    <div className="form-field">
                      <label>
                        <input type="checkbox" checked={acknowledgeWarnings} onChange={(e) => setAcknowledgeWarnings(e.target.checked)} /* form-ok: مربع تأكيد قراءة التحذيرات، لا يُرجع خطأ حقل من الـAPI */ />{" "}
                        {t("acknowledgeWarnings")}
                      </label>
                    </div>
                  )}
                  <FormField name="note" label={t("closeNote")} style={{ maxWidth: "360px" }}>
                    <input value={closeNote} onChange={(e) => setCloseNote(e.target.value)} />
                  </FormField>
                  <button
                    className="primary"
                    disabled={checklistItems.some((item) => item.level === "warn") && !acknowledgeWarnings}
                    onClick={closePeriod}
                  >
                    {t("closePeriod")}
                  </button>
                </>
              )}
            </>
          )}
          <button
            className="secondary"
            style={{ marginInlineStart: "0.5rem" }}
            onClick={() => {
              setChecklistFor(null);
              setChecklistItems(null);
            }}
          >
            {t("cancel")}
          </button>
        </div>
      )}
    </div>
  );
}
