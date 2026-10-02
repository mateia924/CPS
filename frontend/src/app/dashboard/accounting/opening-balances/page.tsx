"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api, fieldErrors, generalError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { StatusBadge } from "@/components/StatusBadge";
import { FormField } from "@/components/FormField";
import { Money } from "@/components/Money";
import { WarningsBanner } from "@/components/WarningsBanner";
import {
  EMPTY_LINE,
  linesToPayload,
  OpeningBalanceLinesEditor,
  type LineDraft,
} from "@/components/OpeningBalanceLinesEditor";
import type {
  AccountTreeNode,
  CostCenter,
  LegalEntity,
  OpeningBalanceEntry,
  OpeningBalanceKind,
  OpeningBalanceStatusRow,
  Paginated,
  Party,
} from "@/lib/types";

function OpeningBalancesContent() {
  const { t } = useLocale();
  const { me } = useAuth();
  const searchParams = useSearchParams();
  const [entities, setEntities] = useState<LegalEntity[]>([]);
  const [accounts, setAccounts] = useState<AccountTreeNode[]>([]);
  const [parties, setParties] = useState<Party[]>([]);
  const [costCenters, setCostCenters] = useState<CostCenter[]>([]);
  const [statusRows, setStatusRows] = useState<OpeningBalanceStatusRow[]>([]);
  const [legalEntityId, setLegalEntityId] = useState(() => searchParams.get("entity") ?? "");
  // Sprint 6.6.1 (item 4): the LIST's own optional entity filter —
  // separate from `legalEntityId` above (the create form's own
  // required field) — defaults to "الكل" so the list itself never
  // silently narrows to just the form's currently-selected entity.
  const [listEntityId, setListEntityId] = useState("");
  const [kind, setKind] = useState<OpeningBalanceKind>(
    () => (searchParams.get("kind") as OpeningBalanceKind) || "initial"
  );
  const [lines, setLines] = useState<LineDraft[]>([{ ...EMPTY_LINE }, { ...EMPTY_LINE }]);
  const [error, setError] = useState<string | null>(null);
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});
  const [warnings, setWarnings] = useState<string[]>([]);
  const [refreshToken, setRefreshToken] = useState(0);

  const showCostCenterUI = !!me && me.features.cost_centers;

  useEffect(() => {
    (async () => {
      const [entityData, tree, partyData, statusData] = await Promise.all([
        api.get<Paginated<LegalEntity>>("/legal-entities/"),
        api.get<AccountTreeNode[]>("/accounts/tree/"),
        api.get<Paginated<Party>>("/parties/"),
        api.get<OpeningBalanceStatusRow[]>("/opening-balances/status/"),
      ]);
      setEntities(entityData.results.filter((entity) => entity.entity_type !== "holding"));
      if (me?.default_legal_entity_id) setLegalEntityId((prev) => prev || me.default_legal_entity_id!);
      setAccounts(tree);
      setParties(partyData.results);
      setStatusRows(statusData);
      if (showCostCenterUI) {
        const ccData = await api.get<Paginated<CostCenter>>("/cost-centers/");
        setCostCenters(ccData.results);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showCostCenterUI, refreshToken]);

  const resetForm = () => {
    setKind("initial");
    setLines([{ ...EMPTY_LINE }, { ...EMPTY_LINE }]);
    setError(null);
    setFieldErr({});
  };

  // Same-currency eyeball total only — the authoritative check is
  // always server-side (readiness/submit); this is just a live hint
  // while filling the form (decision 7's "الفرق الحي").
  const rawDebit = lines.reduce((sum, l) => sum + (parseFloat(l.debitFc) || 0), 0);
  const rawCredit = lines.reduce((sum, l) => sum + (parseFloat(l.creditFc) || 0), 0);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setFieldErr({});
    const payload = { legal_entity: legalEntityId, kind, lines: linesToPayload(lines) };
    try {
      const created = await api.post<OpeningBalanceEntry>("/opening-balances/", payload);
      setWarnings(created.warnings || []);
      resetForm();
      setRefreshToken((n) => n + 1);
    } catch (err) {
      setFieldErr(fieldErrors((err as { body?: unknown }).body));
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  return (
    <div>
      <h1>{t("openingBalancesNav")}</h1>
      <WarningsBanner warnings={warnings} />

      <div className="card">
        <h3>{t("statusByEntity")}</h3>
        <table>
          <thead>
            <tr>
              <th>{t("legalEntity")}</th>
              <th>{t("status")}</th>
              <th>{t("approvedAt")}</th>
            </tr>
          </thead>
          <tbody>
            {statusRows.map((row) => (
              <tr key={row.legal_entity}>
                <td>{row.legal_entity_name}</td>
                <td>
                  {row.current_entry_id ? (
                    <Link href={`/dashboard/accounting/opening-balances/${row.current_entry_id}`}>
                      <StatusBadge status={row.current_entry_status ?? "draft"} />
                    </Link>
                  ) : (
                    t("notApprovedYet")
                  )}
                </td>
                <td>{row.approved_at ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3>{t("createOpeningBalance")}</h3>
        <form onSubmit={onSubmit}>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <FormField name="legal_entity" label={t("legalEntity")} required error={fieldErr.legal_entity} style={{ minWidth: "260px" }}>
              <select value={legalEntityId} onChange={(e) => setLegalEntityId(e.target.value)} required>
                <option value="" disabled>—</option>
                {entities.map((entity) => (
                  <option key={entity.id} value={entity.id}>{entity.code} — {entity.name}</option>
                ))}
              </select>
            </FormField>
            <FormField name="kind" label={t("kind")} error={fieldErr.kind}>
              <select value={kind} onChange={(e) => setKind(e.target.value as OpeningBalanceKind)}>
                <option value="initial">{t("initial")}</option>
                <option value="adjustment">{t("adjustment")}</option>
              </select>
            </FormField>
          </div>

          <OpeningBalanceLinesEditor
            lines={lines}
            onChange={setLines}
            accounts={accounts}
            parties={parties}
            costCenters={costCenters}
            showCostCenterUI={showCostCenterUI}
          />

          <p>
            {t("difference")}: <Money amount={String(rawDebit - rawCredit)} /> ({t("balanced")}: {rawDebit === rawCredit ? "✓" : "✗"})
          </p>

          <WarningsBanner warnings={error ? [error] : []} variant="error" />
          <button className="primary" type="submit">{t("createOpeningBalance")}</button>
        </form>
      </div>

      <FormField name="list_entity_filter" label={t("entityFilter")}>
        <select value={listEntityId} onChange={(e) => setListEntityId(e.target.value)}>
          <option value="">{t("allEntities")}</option>
          {entities.map((entity) => (
            <option key={entity.id} value={entity.id}>{entity.code} — {entity.name}</option>
          ))}
        </select>
      </FormField>

      <DataTable<OpeningBalanceEntry>
        endpoint="/opening-balances/"
        extraParams={{ legal_entity: listEntityId }}
        refreshToken={refreshToken}
        hasActiveToggle={false}
        columns={[
          { key: "legal_entity_name", label: t("legalEntity") },
          { key: "kind", label: t("kind"), render: (row) => t(row.kind) },
          { key: "opening_date", label: t("openingDate") },
          { key: "status", label: t("status"), render: (row) => <StatusBadge status={row.status} /> },
        ]}
        renderExtraActions={(row) => (
          <Link href={`/dashboard/accounting/opening-balances/${row.id}`}>
            <button className="secondary">{t("viewDetails")}</button>
          </Link>
        )}
      />
    </div>
  );
}

export default function OpeningBalancesPage() {
  return (
    <Suspense fallback={null}>
      <OpeningBalancesContent />
    </Suspense>
  );
}
