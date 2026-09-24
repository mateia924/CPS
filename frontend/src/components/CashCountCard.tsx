"use client";

import { useEffect, useState } from "react";
import { api, ApiError, generalError } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import type { CashCount, Paginated } from "@/lib/types";

/** Sprint 5.5 (block 5.5.3, CFO_REVIEW_1 F14): "الجرد" tab on the cash
 * box detail screen. */
export function CashCountCard({ cashBoxId }: { cashBoxId: string }) {
  const { t } = useLocale();
  const [counts, setCounts] = useState<CashCount[]>([]);
  const [showNew, setShowNew] = useState(false);
  const [countDate, setCountDate] = useState("");
  const [countedAmount, setCountedAmount] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    api
      .get<Paginated<CashCount> | CashCount[]>(`/cash-counts/?cash_box=${cashBoxId}`)
      .then((data) => setCounts(Array.isArray(data) ? data : data.results));
  };

  useEffect(load, [cashBoxId]);

  const createCount = async () => {
    setError(null);
    try {
      await api.post(`/cash-counts/`, {
        cash_box: cashBoxId, count_date: countDate, counted_amount: countedAmount,
      });
      setShowNew(false);
      setCountDate("");
      setCountedAmount("");
      load();
    } catch (e) {
      setError(generalError(e instanceof ApiError ? e.body : null, t("couldNotSave")));
    }
  };

  const confirm = async (count: CashCount, createVoucher: boolean) => {
    setError(null);
    let reason = "";
    if (count.difference !== "0.00" && Number(count.difference) !== 0) {
      reason = window.prompt(t("reason")) ?? "";
      if (!reason) return;
    }
    try {
      await api.post(`/cash-counts/${count.id}/confirm/`, {
        reason, create_variance_voucher: createVoucher,
      });
      load();
    } catch (e) {
      setError(generalError(e instanceof ApiError ? e.body : null, t("couldNotSave")));
    }
  };

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3>{t("countTab")}</h3>
        <button className="secondary" onClick={() => setShowNew((v) => !v)}>
          {t("newCount")}
        </button>
      </div>

      {error && <p style={{ color: "var(--danger)" }}>{error}</p>}

      {showNew && (
        <div className="card" style={{ background: "var(--surface-2)" }}>
          <label>
            {t("countDate")}
            <input type="date" value={countDate} onChange={(e) => setCountDate(e.target.value)} />
          </label>
          <label>
            {t("countedAmount")}
            <input value={countedAmount} onChange={(e) => setCountedAmount(e.target.value)} />
          </label>
          <button className="primary" disabled={!countDate || !countedAmount} onClick={createCount}>
            {t("submit")}
          </button>
        </div>
      )}

      <table>
        <thead>
          <tr>
            <th>{t("number")}</th>
            <th>{t("countDate")}</th>
            <th>{t("countedAmount")}</th>
            <th>{t("bookBalanceSnapshot")}</th>
            <th>{t("difference")}</th>
            <th>{t("status")}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {counts.map((c) => (
            <tr key={c.id}>
              <td>{c.number || "—"}</td>
              <td>{c.count_date}</td>
              <td>{c.counted_amount}</td>
              <td>{c.book_balance_snapshot}</td>
              <td style={{ color: Number(c.difference) === 0 ? "inherit" : "var(--danger)" }}>{c.difference}</td>
              <td>{c.status === "confirmed" ? t("confirmed") : t("draft")}</td>
              <td>
                {c.status === "draft" && (
                  <>
                    <button className="secondary" onClick={() => confirm(c, false)}>
                      {t("confirmCount")}
                    </button>{" "}
                    {Number(c.difference) !== 0 && (
                      <button className="secondary" onClick={() => confirm(c, true)}>
                        {t("createVarianceVoucher")}
                      </button>
                    )}
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
