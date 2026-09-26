"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, fieldErrors, generalError } from "@/lib/api";
import { flattenLeafAccounts, type FlatAccountOption } from "@/lib/accounts";
import { FormField } from "@/components/FormField";
import { Money } from "@/components/Money";
import { StatusBadge } from "@/components/StatusBadge";
import { WarningsBanner } from "@/components/WarningsBanner";
import { useLocale } from "@/lib/i18n";
import type {
  Asset,
  AssetDepreciationMethod,
  AccountTreeNode,
  CostCenter,
  LegalEntity,
  Paginated,
  RecurringEntry,
  RecurringInstallmentStatus,
} from "@/lib/types";

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
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});
  const [warnings, setWarnings] = useState<string[]>([]);
  const [rejectReason, setRejectReason] = useState("");
  const [showReject, setShowReject] = useState(false);

  const [inServiceDate, setInServiceDate] = useState("");
  const [method, setMethod] = useState<AssetDepreciationMethod>("straight_line");
  const [decliningRate, setDecliningRate] = useState("");
  const [openingAccum, setOpeningAccum] = useState("0");

  const [additionDate, setAdditionDate] = useState("");
  const [additionAmount, setAdditionAmount] = useState("");
  const [additionDescription, setAdditionDescription] = useState("");
  const [extendLifeMonths, setExtendLifeMonths] = useState("0");
  const [showAddAddition, setShowAddAddition] = useState(false);

  const [accounts, setAccounts] = useState<FlatAccountOption[]>([]);
  const [disposalDate, setDisposalDate] = useState("");
  const [disposalFraction, setDisposalFraction] = useState("1");
  const [disposalProceeds, setDisposalProceeds] = useState("0");
  const [disposalAccountId, setDisposalAccountId] = useState("");
  const [disposalReason, setDisposalReason] = useState("");
  const [showDispose, setShowDispose] = useState(false);

  const [legalEntities, setLegalEntities] = useState<LegalEntity[]>([]);
  const [costCenters, setCostCenters] = useState<CostCenter[]>([]);
  const [transferEntityId, setTransferEntityId] = useState("");
  const [transferCostCenterId, setTransferCostCenterId] = useState("");
  const [showTransfer, setShowTransfer] = useState(false);

  useEffect(() => {
    api.get<AccountTreeNode[]>("/accounts/tree/").then((tree) => setAccounts(flattenLeafAccounts(tree)));
    api.get<Paginated<LegalEntity>>("/legal-entities/").then((data) => setLegalEntities(data.results));
    api.get<Paginated<CostCenter>>("/cost-centers/").then((data) => setCostCenters(data.results));
  }, []);

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
    setFieldErr({});
    try {
      await api.post(`/depreciation-schedules/${schedule!.id}/${action}/`, body);
      setShowReject(false);
      setRejectReason("");
      load();
    } catch (err) {
      setFieldErr(fieldErrors((err as { body?: unknown }).body));
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const startDepreciation = async () => {
    setError(null);
    setFieldErr({});
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
      setFieldErr(fieldErrors((err as { body?: unknown }).body));
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const generateDueNow = async () => {
    setError(null);
    try {
      const result = await api.post<{ generated: number; skipped: number }>(`/assets/${id}/generate-due-now/`);
      setWarnings([
        t("generateDueNowResult")
          .replace("{generated}", String(result.generated))
          .replace("{skipped}", String(result.skipped)),
      ]);
      load();
    } catch (err) {
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const cost = Number(asset.cost_base ?? asset.purchase_cost);
  const accumulatedDepreciation = Number(asset.accumulated_depreciation ?? 0);
  const bookValue = Number(asset.book_value ?? cost);
  const remainingInstallments = (schedule?.installments || []).filter((i) => i.status === "due").length;

  const addAddition = async () => {
    setError(null);
    setFieldErr({});
    try {
      await api.post(`/assets/${id}/additions/`, {
        date: additionDate,
        amount_base: additionAmount,
        description: additionDescription,
        extend_life_months: Number(extendLifeMonths) || 0,
      });
      setShowAddAddition(false);
      setAdditionDate("");
      setAdditionAmount("");
      setAdditionDescription("");
      setExtendLifeMonths("0");
      load();
    } catch (err) {
      setFieldErr(fieldErrors((err as { body?: unknown }).body));
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const disposeAsset = async () => {
    setError(null);
    setFieldErr({});
    try {
      const result = await api.post<{ warnings?: string[] }>(`/assets/${id}/dispose/`, {
        date: disposalDate,
        fraction: disposalFraction,
        proceeds_base: disposalProceeds,
        proceeds_account: disposalAccountId || null,
        reason: disposalReason,
      });
      setWarnings(result.warnings || []);
      setShowDispose(false);
      setDisposalDate("");
      setDisposalFraction("1");
      setDisposalProceeds("0");
      setDisposalAccountId("");
      setDisposalReason("");
      load();
    } catch (err) {
      setFieldErr(fieldErrors((err as { body?: unknown }).body));
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const transferAsset = async () => {
    setError(null);
    setFieldErr({});
    try {
      await api.post(`/assets/${id}/transfer/`, {
        legal_entity: transferEntityId || null,
        cost_center: transferCostCenterId || null,
      });
      setShowTransfer(false);
      setTransferEntityId("");
      setTransferCostCenterId("");
      load();
    } catch (err) {
      setFieldErr(fieldErrors((err as { body?: unknown }).body));
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const disposedFraction = Number(asset.disposed_fraction);

  return (
    <div>
      <button className="secondary" onClick={() => router.push("/dashboard/assets")}>
        ← {t("back")}
      </button>

      <h1 style={{ marginTop: "1rem" }}>
        {asset.code} — {asset.name}{" "}
        <span style={{ fontSize: "0.9rem", color: "var(--muted)" }}>
          {t(asset.status === "under_maintenance" ? "underMaintenance" : asset.status === "disposed" ? "disposed" : "active")}
        </span>{" "}
        {asset.status === "disposed" || disposedFraction >= 1 ? (
          <span
            style={{
              fontSize: "0.8rem", color: "var(--danger)", background: "var(--danger-bg)",
              borderRadius: "var(--radius-pill)", padding: "0.1rem 0.5rem",
            }}
          >
            {t("fullyDisposedBadge")}
          </span>
        ) : disposedFraction > 0 ? (
          <span
            style={{
              fontSize: "0.8rem", color: "var(--warning)", background: "var(--warning-bg)",
              borderRadius: "var(--radius-pill)", padding: "0.1rem 0.5rem",
            }}
          >
            {t("partiallyDisposedBadge")}
          </span>
        ) : null}
      </h1>

      <WarningsBanner warnings={warnings} />
      <WarningsBanner warnings={error ? [error] : []} variant="error" />

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

            {schedule.status === "approved" && (
              <button className="secondary" style={{ marginTop: "0.75rem" }} onClick={generateDueNow}>
                {t("generateDueNow")}
              </button>
            )}

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
                  <div style={{ marginTop: "0.5rem", display: "flex", gap: "0.5rem", alignItems: "start" }}>
                    <FormField name="reason" required error={fieldErr.reason} style={{ minWidth: "260px" }}>
                      <input
                        value={rejectReason}
                        onChange={(e) => setRejectReason(e.target.value)}
                        required
                      />
                    </FormField>
                    <button
                      className="secondary" style={{ marginTop: "1.6rem" }}
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

            <h3 style={{ marginTop: "1rem" }}>{t("additionsTab")}</h3>
            <button className="secondary" onClick={() => setShowAddAddition((v) => !v)}>
              {t("addAddition")}
            </button>
            {showAddAddition && (
              <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "0.5rem" }}>
                <FormField name="date" label={t("additionDate")} error={fieldErr.date}>
                  <input type="date" value={additionDate} onChange={(e) => setAdditionDate(e.target.value)} />
                </FormField>
                <FormField name="amount_base" label={t("additionAmount")} error={fieldErr.amount_base}>
                  <input
                    type="number" step="0.01" value={additionAmount}
                    onChange={(e) => setAdditionAmount(e.target.value)}
                  />
                </FormField>
                <FormField name="extend_life_months" error={fieldErr.extend_life_months}>
                  <input
                    type="number" value={extendLifeMonths}
                    onChange={(e) => setExtendLifeMonths(e.target.value)}
                  />
                </FormField>
                <FormField name="description" error={fieldErr.description}>
                  <input value={additionDescription} onChange={(e) => setAdditionDescription(e.target.value)} />
                </FormField>
                <button className="primary" onClick={addAddition}>{t("save")}</button>
              </div>
            )}

            <h4 style={{ marginTop: "0.75rem" }}>{t("additionsHistory")}</h4>
            {asset.additions.length === 0 ? (
              <p>{t("noAdditionsYet")}</p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>{t("additionDate")}</th>
                    <th>{t("additionAmount")}</th>
                    <th>{t("extendLifeMonths")}</th>
                    <th>{t("description")}</th>
                  </tr>
                </thead>
                <tbody>
                  {asset.additions.map((addition) => (
                    <tr key={addition.id}>
                      <td>{addition.date}</td>
                      <td><Money amount={addition.amount_base} /></td>
                      <td>{addition.extend_life_months}</td>
                      <td>{addition.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        ) : (
          <>
            <p>{t("noDepreciationSchedule")}</p>
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
              <FormField name="in_service_date" error={fieldErr.in_service_date}>
                <input type="date" value={inServiceDate} onChange={(e) => setInServiceDate(e.target.value)} />
              </FormField>
              <FormField name="depreciation_method" error={fieldErr.depreciation_method}>
                <select
                  value={method}
                  onChange={(e) => {
                    const nextMethod = e.target.value as AssetDepreciationMethod;
                    setMethod(nextMethod);
                    // Decision 5: "تُقترح تلقائيًا في الفورم بقيمة
                    // المضاعف = 200 ÷ (العمر بالسنوات) بحد أقصى 99" —
                    // only fills an empty field, never overwrites a
                    // rate the accountant already typed.
                    if (nextMethod === "declining_balance" && !decliningRate && asset.useful_life_months) {
                      const years = asset.useful_life_months / 12;
                      const suggested = Math.min(99, 200 / years);
                      setDecliningRate(suggested.toFixed(2)); // money-ok: a percentage rate, not a money amount
                    }
                  }}
                >
                  <option value="straight_line">{t("straightLine")}</option>
                  <option value="declining_balance">{t("decliningBalance")}</option>
                </select>
              </FormField>
              {method === "declining_balance" && (
                <FormField name="declining_balance_rate" error={fieldErr.declining_balance_rate}>
                  <input
                    type="number" step="0.01" value={decliningRate}
                    onChange={(e) => setDecliningRate(e.target.value)}
                  />
                </FormField>
              )}
              <FormField name="opening_accumulated_depreciation" error={fieldErr.opening_accumulated_depreciation}>
                <input
                  type="number" step="0.01" value={openingAccum}
                  onChange={(e) => setOpeningAccum(e.target.value)}
                />
              </FormField>
            </div>
            <button className="primary" style={{ marginTop: "0.75rem" }} onClick={startDepreciation}>
              {t("startDepreciation")}
            </button>
          </>
        )}
      </div>

      {asset.status !== "disposed" && disposedFraction < 1 && (
        <div className="card">
          <h3>{t("disposalsTab")}</h3>
          <button className="secondary" onClick={() => setShowDispose((v) => !v)}>
            {t("disposeAsset")}
          </button>
          {showDispose && (
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "0.5rem" }}>
              <FormField name="date" label={t("disposalDate")} error={fieldErr.date}>
                <input type="date" value={disposalDate} onChange={(e) => setDisposalDate(e.target.value)} />
              </FormField>
              <FormField name="fraction" label={t("disposalFraction")} error={fieldErr.fraction}>
                <input
                  type="number" step="0.0001" min="0" max="1" value={disposalFraction}
                  onChange={(e) => setDisposalFraction(e.target.value)}
                />
              </FormField>
              <FormField name="proceeds_base" label={t("disposalProceeds")} error={fieldErr.proceeds_base}>
                <input
                  type="number" step="0.01" value={disposalProceeds}
                  onChange={(e) => setDisposalProceeds(e.target.value)}
                />
              </FormField>
              {Number(disposalProceeds) > 0 && (
                <FormField name="proceeds_account" label={t("disposalProceedsAccount")} error={fieldErr.proceeds_account}>
                  <select value={disposalAccountId} onChange={(e) => setDisposalAccountId(e.target.value)}>
                    <option value="">—</option>
                    {accounts.map((account) => (
                      <option key={account.id} value={account.id}>{account.label}</option>
                    ))}
                  </select>
                </FormField>
              )}
              <FormField name="reason" label={t("disposalReason")} error={fieldErr.reason}>
                <input value={disposalReason} onChange={(e) => setDisposalReason(e.target.value)} />
              </FormField>
              <button className="primary" onClick={disposeAsset}>{t("save")}</button>
            </div>
          )}

          <h4 style={{ marginTop: "0.75rem" }}>{t("disposalsHistory")}</h4>
          {asset.disposals.length === 0 ? (
            <p>{t("noDisposalsYet")}</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>{t("disposalDate")}</th>
                  <th>{t("disposalFraction")}</th>
                  <th>{t("disposalProceeds")}</th>
                  <th>{t("gainLoss")}</th>
                  <th>{t("status")}</th>
                </tr>
              </thead>
              <tbody>
                {asset.disposals.map((disposal) => (
                  <tr key={disposal.id}>
                    <td>{disposal.date}</td>
                    <td>{disposal.fraction}</td>
                    <td><Money amount={disposal.proceeds_base} /></td>
                    <td><Money amount={disposal.gain_loss} /></td>
                    <td>{disposal.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {asset.status !== "disposed" && (
        <div className="card">
          <h3>{t("transfersTab")}</h3>
          <button className="secondary" onClick={() => setShowTransfer((v) => !v)}>
            {t("transferAsset")}
          </button>
          {showTransfer && (
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "0.5rem" }}>
              <FormField name="legal_entity" label={t("transferLegalEntity")} error={fieldErr.legal_entity}>
                <select value={transferEntityId} onChange={(e) => setTransferEntityId(e.target.value)}>
                  <option value="">—</option>
                  {legalEntities.map((entity) => (
                    <option key={entity.id} value={entity.id}>{entity.code} — {entity.name}</option>
                  ))}
                </select>
              </FormField>
              <FormField name="cost_center" label={t("transferCostCenter")} error={fieldErr.cost_center}>
                <select value={transferCostCenterId} onChange={(e) => setTransferCostCenterId(e.target.value)}>
                  <option value="">—</option>
                  {costCenters.map((cc) => (
                    <option key={cc.id} value={cc.id}>{cc.code} — {cc.name}</option>
                  ))}
                </select>
              </FormField>
              <button className="primary" onClick={transferAsset}>{t("save")}</button>
            </div>
          )}

          <h4 style={{ marginTop: "0.75rem" }}>{t("transfersHistory")}</h4>
          {asset.transfers.length === 0 ? (
            <p>{t("noTransfersYet")}</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>{t("transferLegalEntity")}</th>
                  <th>{t("transferCostCenter")}</th>
                  <th>{t("date")}</th>
                </tr>
              </thead>
              <tbody>
                {asset.transfers.map((transfer) => (
                  <tr key={transfer.id}>
                    <td>
                      {transfer.from_legal_entity !== transfer.to_legal_entity
                        ? `${transfer.from_legal_entity} → ${transfer.to_legal_entity}`
                        : "—"}
                    </td>
                    <td>
                      {transfer.from_cost_center !== transfer.to_cost_center
                        ? `${transfer.from_cost_center || "—"} → ${transfer.to_cost_center || "—"}`
                        : "—"}
                    </td>
                    <td>{new Date(transfer.created_at).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
