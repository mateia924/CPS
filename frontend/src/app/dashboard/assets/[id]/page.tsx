"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, generalError } from "@/lib/api";
import { Money } from "@/components/Money";
import { StatusBadge } from "@/components/StatusBadge";
import { WarningsBanner } from "@/components/WarningsBanner";
import { useLocale } from "@/lib/i18n";
import type { Asset, AssetDepreciationMethod, RecurringEntry, RecurringInstallmentStatus } from "@/lib/types";

const INSTALLMENT_STATUS_LABEL: Record<RecurringInstallmentStatus, string> = {
  due: "dueStatus",
  generated: "generatedStatus",
  skipped: "skippedStatus",
  cancelled: "cancelled",
};

export default function AssetDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { t } = useLocale();
  const [asset, setAsset] = useState<Asset | null>(null);
  const [schedule, setSchedule] = useState<RecurringEntry | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [rejectReason, setRejectReason] = useState("");
  const [showReject, setShowReject] = useState(false);

  const [inServiceDate, setInServiceDate] = useState("");
  const [method, setMethod] = useState<AssetDepreciationMethod>("straight_line");
  const [decliningRate, setDecliningRate] = useState("");
  const [openingAccum, setOpeningAccum] = useState("0");

  const load = async () => {
    const loadedAsset = await api.get<Asset>(`/assets/${id}/`);
    setAsset(loadedAsset);
    setInServiceDate(loadedAsset.in_service_date || loadedAsset.purchase_date);
    setMethod(loadedAsset.depreciation_method);
    setDecliningRate(loadedAsset.declining_balance_rate || "");
    setOpeningAccum(loadedAsset.opening_accumulated_depreciation);
    if (loadedAsset.depreciation_entry) {
      setSchedule(await api.get<RecurringEntry>(`/depreciation-schedules/${loadedAsset.depreciation_entry}/`));
    } else {
      setSchedule(null);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (!asset) return null;

  const runScheduleAction = async (action: string, body?: Record<string, unknown>) => {
    setError(null);
    try {
      await api.post(`/depreciation-schedules/${schedule!.id}/${action}/`, body);
      setShowReject(false);
      setRejectReason("");
      load();
    } catch (err) {
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const startDepreciation = async () => {
    setError(null);
    try {
      await api.patch(`/assets/${id}/`, {
        in_service_date: inServiceDate,
        depreciation_method: method,
        declining_balance_rate: method === "declining_balance" ? decliningRate : null,
        opening_accumulated_depreciation: openingAccum,
      });
      const started = await api.post<Asset & { warnings: string[] }>(`/assets/${id}/start-depreciation/`);
      setWarnings(started.warnings || []);
      load();
    } catch (err) {
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const cost = Number(asset.cost_base ?? asset.purchase_cost);
  const generatedTotal = (schedule?.installments || [])
    .filter((i) => i.status === "generated")
    .reduce((sum, i) => sum + Number(i.amount_base), 0);
  const accumulatedDepreciation = Number(asset.opening_accumulated_depreciation) + generatedTotal;
  const bookValue = cost - accumulatedDepreciation;
  const remainingInstallments = (schedule?.installments || []).filter((i) => i.status === "due").length;

  return (
    <div>
      <button className="secondary" onClick={() => router.push("/dashboard/assets")}>
        ← {t("back")}
      </button>

      <h1 style={{ marginTop: "1rem" }}>
        {asset.code} — {asset.name}{" "}
        <span style={{ fontSize: "0.9rem", color: "var(--muted)" }}>
          {t(asset.status === "under_maintenance" ? "underMaintenance" : asset.status === "disposed" ? "disposed" : "active")}
        </span>
      </h1>

      <WarningsBanner warnings={warnings} />
      {error && <p className="error-text">{error}</p>}

      <div className="card">
        <p>{t("category")}: {t(asset.category)}</p>
        <p>{t("purchaseDate")}: {asset.purchase_date}</p>
        <p>{t("purchaseCost")}: <Money amount={asset.purchase_cost} currency={asset.currency} /></p>
        <p>{t("usefulLifeMonths")}: {asset.useful_life_months ?? "—"}</p>
        <p>{t("salvageValue")}: <Money amount={asset.salvage_value} currency={asset.currency} /></p>
        <p>{t("isDepreciable")}: {asset.is_depreciable ? t("yes") : t("no")}</p>
      </div>

      <div className="card">
        <h3>{t("depreciationTab")}</h3>

        {schedule ? (
          <>
            <p><StatusBadge status={schedule.status} /></p>
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
              <div className="card" style={{ flex: 1 }}>
                <div>{t("costCard")}</div>
                <strong><Money amount={cost} /></strong>
              </div>
              <div className="card" style={{ flex: 1 }}>
                <div>{t("accumulatedDepreciationCard")}</div>
                <strong><Money amount={accumulatedDepreciation} /></strong>
              </div>
              <div className="card" style={{ flex: 1 }}>
                <div>{t("bookValueCard")}</div>
                <strong><Money amount={bookValue} /></strong>
              </div>
              <div className="card" style={{ flex: 1 }}>
                <div>{t("remainingInstallmentsCard")}</div>
                <strong>{remainingInstallments}</strong>
              </div>
            </div>

            {schedule.status === "pending_approval" && (
              <div style={{ marginTop: "0.75rem" }}>
                <button className="primary" onClick={() => runScheduleAction("approve")}>{t("approve")}</button>
                <button
                  className="secondary" style={{ marginInlineStart: "0.5rem" }}
                  onClick={() => runScheduleAction("withdraw")}
                >
                  {t("withdraw")}
                </button>
                <button
                  className="secondary" style={{ marginInlineStart: "0.5rem" }}
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
                      className="secondary" style={{ marginInlineStart: "0.5rem" }}
                      onClick={() => runScheduleAction("reject", { reason: rejectReason })}
                    >
                      {t("save")}
                    </button>
                  </div>
                )}
              </div>
            )}

            <table style={{ marginTop: "0.75rem" }}>
              <thead>
                <tr>
                  <th>{t("seq")}</th>
                  <th>{t("dueDate")}</th>
                  <th>{t("amount")}</th>
                  <th>{t("status")}</th>
                  <th>{t("post")}</th>
                </tr>
              </thead>
              <tbody>
                {schedule.installments.map((installment) => (
                  <tr key={installment.id}>
                    <td>{installment.seq}</td>
                    <td>{installment.due_date}</td>
                    <td><Money amount={installment.amount_base} /></td>
                    <td>{t(INSTALLMENT_STATUS_LABEL[installment.status])}</td>
                    <td>
                      {installment.journal_entry && (
                        <a href={`/dashboard/accounting/journal-entries/${installment.journal_entry}`}>
                          {t("viewDetails")}
                        </a>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : (
          <>
            <p>{t("noDepreciationSchedule")}</p>
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
              <div className="form-field">
                <label>{t("inServiceDate")}</label>
                <input type="date" value={inServiceDate} onChange={(e) => setInServiceDate(e.target.value)} />
              </div>
              <div className="form-field">
                <label>{t("depreciationMethod")}</label>
                <select value={method} onChange={(e) => setMethod(e.target.value as AssetDepreciationMethod)}>
                  <option value="straight_line">{t("straightLine")}</option>
                  <option value="declining_balance">{t("decliningBalance")}</option>
                </select>
              </div>
              {method === "declining_balance" && (
                <div className="form-field">
                  <label>{t("decliningBalanceRate")}</label>
                  <input
                    type="number" step="0.01" value={decliningRate}
                    onChange={(e) => setDecliningRate(e.target.value)}
                  />
                </div>
              )}
              <div className="form-field">
                <label>{t("openingAccumulatedDepreciation")}</label>
                <input
                  type="number" step="0.01" value={openingAccum}
                  onChange={(e) => setOpeningAccum(e.target.value)}
                />
              </div>
            </div>
            <button className="primary" style={{ marginTop: "0.75rem" }} onClick={startDepreciation}>
              {t("startDepreciation")}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
