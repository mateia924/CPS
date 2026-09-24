"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, generalError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { StatusBadge } from "@/components/StatusBadge";
import { Money } from "@/components/Money";
import { flattenLeafAccounts, type FlatAccountOption } from "@/lib/accounts";
import type {
  AccountTreeNode,
  CostCenter,
  FiscalPeriod,
  LegalEntity,
  Paginated,
  RecurringEntry,
  RecurringEntryKind,
  RecurringInstallmentPreviewRow,
} from "@/lib/types";

const KIND_LABEL: Record<RecurringEntryKind, string> = {
  prepaid_expense: "prepaidExpenseKind",
  deferred_revenue: "deferredRevenueKind",
  accrual: "accrualKind",
  other: "other",
  depreciation: "other",
};

export default function RecurringEntriesPage() {
  const { t } = useLocale();
  const { me } = useAuth();
  const [entities, setEntities] = useState<LegalEntity[]>([]);
  const [accounts, setAccounts] = useState<FlatAccountOption[]>([]);
  const [costCenters, setCostCenters] = useState<CostCenter[]>([]);
  const [periods, setPeriods] = useState<FiscalPeriod[]>([]);
  const [legalEntityId, setLegalEntityId] = useState("");
  const [kind, setKind] = useState<RecurringEntryKind>("prepaid_expense");
  const [description, setDescription] = useState("");
  const [fromAccount, setFromAccount] = useState("");
  const [toAccount, setToAccount] = useState("");
  const [costCenter, setCostCenter] = useState("");
  const [totalAmount, setTotalAmount] = useState("");
  const [installmentsCount, setInstallmentsCount] = useState("12");
  const [firstPeriod, setFirstPeriod] = useState("");
  const [preview, setPreview] = useState<RecurringInstallmentPreviewRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);

  const showCostCenterUI = !!me && me.features.cost_centers;

  useEffect(() => {
    (async () => {
      const [entityData, tree, periodData] = await Promise.all([
        api.get<Paginated<LegalEntity>>("/legal-entities/"),
        api.get<AccountTreeNode[]>("/accounts/tree/"),
        api.get<Paginated<FiscalPeriod>>("/fiscal-periods/?ordering=start_date"),
      ]);
      setEntities(entityData.results.filter((entity) => entity.entity_type !== "holding"));
      if (me?.legal_entity_ids[0]) setLegalEntityId((prev) => prev || me.legal_entity_ids[0]);
      setAccounts(flattenLeafAccounts(tree));
      setPeriods(periodData.results);
      if (showCostCenterUI) {
        const ccData = await api.get<Paginated<CostCenter>>("/cost-centers/");
        setCostCenters(ccData.results);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showCostCenterUI]);

  const payload = () => ({
    legal_entity: legalEntityId,
    kind,
    description,
    from_account: fromAccount,
    to_account: toAccount,
    ...(costCenter ? { cost_center: costCenter } : {}),
    total_amount_base: totalAmount,
    installments_count: Number(installmentsCount),
    first_period: firstPeriod,
  });

  const showPreview = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      const rows = await api.post<RecurringInstallmentPreviewRow[]>("/recurring-entries/preview/", payload());
      setPreview(rows);
    } catch (err) {
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const onSubmit = async () => {
    setError(null);
    try {
      await api.post("/recurring-entries/", payload());
      setDescription("");
      setFromAccount("");
      setToAccount("");
      setCostCenter("");
      setTotalAmount("");
      setInstallmentsCount("12");
      setPreview(null);
      setRefreshToken((n) => n + 1);
    } catch (err) {
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const generateDueNow = async () => {
    await api.post("/recurring-entries/generate-due/");
    setRefreshToken((n) => n + 1);
  };

  return (
    <div>
      <h1>{t("recurringEntriesNav")}</h1>

      <div className="card">
        <h3>{t("createRecurringEntry")}</h3>
        <form onSubmit={showPreview}>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <div className="form-field" style={{ minWidth: "220px" }}>
              <label>{t("legalEntity")}</label>
              <select value={legalEntityId} onChange={(e) => setLegalEntityId(e.target.value)} required>
                <option value="" disabled>—</option>
                {entities.map((entity) => (
                  <option key={entity.id} value={entity.id}>{entity.code} — {entity.name}</option>
                ))}
              </select>
            </div>
            <div className="form-field">
              <label>{t("kind")}</label>
              <select value={kind} onChange={(e) => setKind(e.target.value as RecurringEntryKind)}>
                <option value="prepaid_expense">{t("prepaidExpenseKind")}</option>
                <option value="deferred_revenue">{t("deferredRevenueKind")}</option>
                <option value="accrual">{t("accrualKind")}</option>
                <option value="other">{t("other")}</option>
              </select>
            </div>
            <div className="form-field" style={{ flex: 1, minWidth: "220px" }}>
              <label>{t("description")}</label>
              <input value={description} onChange={(e) => setDescription(e.target.value)} required />
            </div>
          </div>

          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "0.5rem" }}>
            <div className="form-field" style={{ flex: 1, minWidth: "200px" }}>
              <label>{t("toAccount")}</label>
              <select value={toAccount} onChange={(e) => setToAccount(e.target.value)} required>
                <option value="" disabled>—</option>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>{a.label}</option>
                ))}
              </select>
            </div>
            <div className="form-field" style={{ flex: 1, minWidth: "200px" }}>
              <label>{t("fromAccount")}</label>
              <select value={fromAccount} onChange={(e) => setFromAccount(e.target.value)} required>
                <option value="" disabled>—</option>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>{a.label}</option>
                ))}
              </select>
            </div>
            {showCostCenterUI && (
              <div className="form-field" style={{ minWidth: "160px" }}>
                <label>{t("costCenter")}</label>
                <select value={costCenter} onChange={(e) => setCostCenter(e.target.value)}>
                  <option value="">{t("none")}</option>
                  {costCenters.map((cc) => (
                    <option key={cc.id} value={cc.id}>{cc.code} — {cc.name}</option>
                  ))}
                </select>
              </div>
            )}
          </div>

          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "0.5rem" }}>
            <div className="form-field" style={{ width: "160px" }}>
              <label>{t("total")}</label>
              <input type="number" step="0.01" value={totalAmount} onChange={(e) => setTotalAmount(e.target.value)} required />
            </div>
            <div className="form-field" style={{ width: "140px" }}>
              <label>{t("installmentsCount")}</label>
              <input type="number" min={1} value={installmentsCount} onChange={(e) => setInstallmentsCount(e.target.value)} required />
            </div>
            <div className="form-field" style={{ minWidth: "220px" }}>
              <label>{t("firstPeriod")}</label>
              <select value={firstPeriod} onChange={(e) => setFirstPeriod(e.target.value)} required>
                <option value="" disabled>—</option>
                {periods.map((p) => (
                  <option key={p.id} value={p.id}>{p.start_date} — {p.end_date}</option>
                ))}
              </select>
            </div>
          </div>

          {error && <p className="error-text">{error}</p>}
          <button className="secondary" type="submit" style={{ marginTop: "0.75rem" }}>
            {t("previewSchedule")}
          </button>

          {preview && (
            <div style={{ marginTop: "0.75rem" }}>
              <table>
                <thead>
                  <tr>
                    <th>{t("seq")}</th>
                    <th>{t("dueDate")}</th>
                    <th>{t("amount")}</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.map((row) => (
                    <tr key={row.seq}>
                      <td>{row.seq}</td>
                      <td>{row.due_date}</td>
                      <td><Money amount={row.amount_base} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button className="primary" type="button" style={{ marginTop: "0.5rem" }} onClick={onSubmit}>
                {t("createRecurringEntry")}
              </button>
            </div>
          )}
        </form>
      </div>

      <button className="secondary" onClick={generateDueNow} style={{ marginBottom: "0.75rem" }}>
        {t("generateDueNow")}
      </button>

      <DataTable<RecurringEntry>
        endpoint="/recurring-entries/"
        refreshToken={refreshToken}
        hasActiveToggle={false}
        columns={[
          { key: "number", label: t("number") },
          { key: "legal_entity_name", label: t("legalEntity") },
          { key: "description", label: t("description") },
          { key: "kind", label: t("kind"), render: (row) => t(KIND_LABEL[row.kind]) },
          { key: "status", label: t("status"), render: (row) => <StatusBadge status={row.status} /> },
        ]}
        renderExtraActions={(row) => (
          <Link href={`/dashboard/accounting/recurring-entries/${row.id}`}>
            <button className="secondary">{t("viewDetails")}</button>
          </Link>
        )}
      />
    </div>
  );
}
