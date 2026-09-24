"use client";

import { useEffect, useState } from "react";
import { api, generalError } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import type { FiscalPeriod, FiscalPeriodicStatus, FiscalYear, Paginated } from "@/lib/types";

const STATUS_LABEL_KEY: Record<FiscalPeriodicStatus, string> = {
  open: "periodOpen",
  closed: "periodClosed",
  locked: "periodLocked",
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
  const [actionError, setActionError] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);

  const load = () => {
    api.get<Paginated<FiscalYear>>("/fiscal-years/").then((data) => setYears(data.results));
  };

  useEffect(load, [refreshToken]);

  const submitCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
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
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const runPeriodAction = async (period: FiscalPeriod, action: "close" | "reopen" | "lock", payload: Record<string, string>) => {
    setActionError(null);
    try {
      await api.post(`/fiscal-periods/${period.id}/${action}/`, payload);
      setRefreshToken((n) => n + 1);
    } catch (err) {
      setActionError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const closePeriod = (period: FiscalPeriod) => {
    const note = window.prompt(t("closeNote")) || "";
    runPeriodAction(period, "close", { note });
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
              <div className="form-field">
                <label>{t("fiscalYearName")}</label>
                <input value={name} onChange={(e) => setName(e.target.value)} required />
              </div>
              <div className="form-field">
                <label>{t("periodStart")}</label>
                <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} required />
              </div>
              <div className="form-field">
                <label>{t("periodEnd")}</label>
                <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} required />
              </div>
              <div className="form-field">
                <label>{t("periodLength")}</label>
                <select value={periodLength} onChange={(e) => setPeriodLength(e.target.value as typeof periodLength)}>
                  <option value="monthly">{t("monthly")}</option>
                  <option value="quarterly">{t("quarterly")}</option>
                  <option value="custom">{t("custom")}</option>
                </select>
              </div>
              {periodLength === "custom" && (
                <div className="form-field" style={{ flex: 1, minWidth: "260px" }}>
                  <label>{t("custom")} — end dates (YYYY-MM-DD, comma-separated)</label>
                  <input value={customDates} onChange={(e) => setCustomDates(e.target.value)} />
                </div>
              )}
            </div>
            {error && <p className="error-text">{error}</p>}
            <button className="primary" type="submit" style={{ marginTop: "0.5rem" }}>
              {t("save")}
            </button>
          </form>
        )}
      </div>

      {actionError && <p className="error-text">{actionError}</p>}

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
                        <button className="secondary" onClick={() => closePeriod(period)}>
                          {t("closePeriod")}
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
    </div>
  );
}
