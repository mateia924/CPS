"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api, generalError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { StatusBadge } from "@/components/StatusBadge";
import { Money } from "@/components/Money";
import type {
  AccountTreeNode,
  CostCenter,
  LegalEntity,
  OpeningBalanceEntry,
  OpeningBalanceKind,
  OpeningBalanceStatusRow,
  Paginated,
  Party,
  PartyRoleType,
} from "@/lib/types";

interface OpenItemDraft {
  ref: string;
  date: string;
  amountFc: string;
}

interface LineDraft {
  mode: "account" | "party";
  account: string;
  party: string;
  partyRole: PartyRoleType | "";
  costCenter: string;
  currency: string;
  exchangeRate: string;
  debitFc: string;
  creditFc: string;
  openItems: OpenItemDraft[];
  notes: string;
}

const EMPTY_LINE: LineDraft = {
  mode: "account", account: "", party: "", partyRole: "", costCenter: "",
  currency: "", exchangeRate: "", debitFc: "", creditFc: "", openItems: [], notes: "",
};

const PARTY_ROLES: { value: PartyRoleType; labelKey: string }[] = [
  { value: "customer", labelKey: "customerRole" },
  { value: "supplier", labelKey: "supplierRole" },
  { value: "employee", labelKey: "employeeRole" },
  { value: "affiliate", labelKey: "affiliateRole" },
];

/** Decision 6: only balance-sheet leaf accounts belong in the picker —
 * the backend rejects revenue/expense lines with 400, this just keeps
 * the dropdown from offering them in the first place. */
function balanceSheetLeafAccounts(nodes: AccountTreeNode[]): AccountTreeNode[] {
  const out: AccountTreeNode[] = [];
  for (const node of nodes) {
    if (node.children.length === 0) {
      if (node.type === "asset" || node.type === "liability" || node.type === "equity") out.push(node);
    } else {
      out.push(...balanceSheetLeafAccounts(node.children));
    }
  }
  return out;
}

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
  const [kind, setKind] = useState<OpeningBalanceKind>(
    () => (searchParams.get("kind") as OpeningBalanceKind) || "initial"
  );
  const [lines, setLines] = useState<LineDraft[]>([{ ...EMPTY_LINE }, { ...EMPTY_LINE }]);
  const [error, setError] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);

  const showCostCenterUI = !!me && me.features.cost_centers;
  const leafAccounts = balanceSheetLeafAccounts(accounts);

  useEffect(() => {
    (async () => {
      const [entityData, tree, partyData, statusData] = await Promise.all([
        api.get<Paginated<LegalEntity>>("/legal-entities/"),
        api.get<AccountTreeNode[]>("/accounts/tree/"),
        api.get<Paginated<Party>>("/parties/"),
        api.get<OpeningBalanceStatusRow[]>("/opening-balances/status/"),
      ]);
      setEntities(entityData.results.filter((entity) => entity.entity_type !== "holding"));
      if (me?.legal_entity_ids[0]) setLegalEntityId((prev) => prev || me.legal_entity_ids[0]);
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

  const addLine = () => setLines([...lines, { ...EMPTY_LINE }]);
  const updateLine = (index: number, patch: Partial<LineDraft>) => {
    setLines(lines.map((line, i) => (i === index ? { ...line, ...patch } : line)));
  };
  const removeLine = (index: number) => setLines(lines.filter((_, i) => i !== index));

  const addOpenItem = (index: number) => {
    updateLine(index, { openItems: [...lines[index].openItems, { ref: "", date: "", amountFc: "" }] });
  };
  const updateOpenItem = (index: number, itemIndex: number, patch: Partial<OpenItemDraft>) => {
    updateLine(index, {
      openItems: lines[index].openItems.map((item, i) => (i === itemIndex ? { ...item, ...patch } : item)),
    });
  };
  const removeOpenItem = (index: number, itemIndex: number) => {
    updateLine(index, { openItems: lines[index].openItems.filter((_, i) => i !== itemIndex) });
  };

  const resetForm = () => {
    setKind("initial");
    setLines([{ ...EMPTY_LINE }, { ...EMPTY_LINE }]);
    setError(null);
  };

  // Same-currency eyeball total only — the authoritative check is
  // always server-side (readiness/submit); this is just a live hint
  // while filling the form (decision 7's "الفرق الحي").
  const rawDebit = lines.reduce((sum, l) => sum + (parseFloat(l.debitFc) || 0), 0);
  const rawCredit = lines.reduce((sum, l) => sum + (parseFloat(l.creditFc) || 0), 0);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const payload = {
      legal_entity: legalEntityId,
      kind,
      lines: lines
        .filter((l) => (l.mode === "account" ? l.account : l.party) && (l.debitFc || l.creditFc))
        .map((l) => ({
          ...(l.mode === "account" ? { account: l.account } : { party: l.party, party_role: l.partyRole }),
          ...(l.costCenter ? { cost_center: l.costCenter } : {}),
          ...(l.currency ? { currency: l.currency } : {}),
          ...(l.exchangeRate ? { exchange_rate: l.exchangeRate } : {}),
          debit_fc: l.debitFc || "0",
          credit_fc: l.creditFc || "0",
          ...(l.openItems.length
            ? {
                open_items: l.openItems
                  .filter((i) => i.ref && i.date && i.amountFc)
                  .map((i) => ({ ref: i.ref, date: i.date, amount_fc: i.amountFc })),
              }
            : {}),
          notes: l.notes,
        })),
    };
    try {
      await api.post("/opening-balances/", payload);
      resetForm();
      setRefreshToken((n) => n + 1);
    } catch (err) {
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  return (
    <div>
      <h1>{t("openingBalancesNav")}</h1>

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
                <td>{row.approved ? t("approved") : t("notApprovedYet")}</td>
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
            <div className="form-field" style={{ minWidth: "260px" }}>
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
              <select value={kind} onChange={(e) => setKind(e.target.value as OpeningBalanceKind)}>
                <option value="initial">{t("initial")}</option>
                <option value="adjustment">{t("adjustment")}</option>
              </select>
            </div>
          </div>

          {lines.map((line, i) => (
            <div key={i} className="card" style={{ background: "var(--surface-2, transparent)" }}>
              <div style={{ display: "flex", gap: "0.75rem", alignItems: "end", flexWrap: "wrap" }}>
                <div className="form-field">
                  <label>{t("lineByAccount")} / {t("lineByParty")}</label>
                  <select
                    value={line.mode}
                    onChange={(e) => updateLine(i, { mode: e.target.value as "account" | "party" })}
                  >
                    <option value="account">{t("lineByAccount")}</option>
                    <option value="party">{t("lineByParty")}</option>
                  </select>
                </div>

                {line.mode === "account" ? (
                  <div className="form-field" style={{ flex: 1, minWidth: "220px" }}>
                    <label>{t("account")}</label>
                    <select value={line.account} onChange={(e) => updateLine(i, { account: e.target.value })} required>
                      <option value="" disabled>—</option>
                      {leafAccounts.map((a) => (
                        <option key={a.id} value={a.id}>{a.code} — {a.name}</option>
                      ))}
                    </select>
                  </div>
                ) : (
                  <>
                    <div className="form-field" style={{ flex: 1, minWidth: "180px" }}>
                      <label>{t("party")}</label>
                      <select value={line.party} onChange={(e) => updateLine(i, { party: e.target.value })} required>
                        <option value="" disabled>—</option>
                        {parties.map((p) => (
                          <option key={p.id} value={p.id}>{p.code} — {p.name}</option>
                        ))}
                      </select>
                    </div>
                    <div className="form-field" style={{ minWidth: "160px" }}>
                      <label>{t("partyRole")}</label>
                      <select
                        value={line.partyRole}
                        onChange={(e) => updateLine(i, { partyRole: e.target.value as PartyRoleType })}
                        required
                      >
                        <option value="" disabled>—</option>
                        {PARTY_ROLES.map((r) => (
                          <option key={r.value} value={r.value}>{t(r.labelKey)}</option>
                        ))}
                      </select>
                    </div>
                  </>
                )}

                {showCostCenterUI && (
                  <div className="form-field" style={{ minWidth: "160px" }}>
                    <label>{t("costCenter")}</label>
                    <select value={line.costCenter} onChange={(e) => updateLine(i, { costCenter: e.target.value })}>
                      <option value="">{t("none")}</option>
                      {costCenters.map((cc) => (
                        <option key={cc.id} value={cc.id}>{cc.code} — {cc.name}</option>
                      ))}
                    </select>
                  </div>
                )}

                <div className="form-field" style={{ width: "90px" }}>
                  <label>{t("currency")}</label>
                  <input value={line.currency} onChange={(e) => updateLine(i, { currency: e.target.value })} maxLength={3} />
                </div>
                <div className="form-field" style={{ width: "130px" }}>
                  <label>{t("debitFc")}</label>
                  <input type="number" step="0.01" value={line.debitFc} onChange={(e) => updateLine(i, { debitFc: e.target.value })} />
                </div>
                <div className="form-field" style={{ width: "130px" }}>
                  <label>{t("creditFc")}</label>
                  <input type="number" step="0.01" value={line.creditFc} onChange={(e) => updateLine(i, { creditFc: e.target.value })} />
                </div>
                <button type="button" className="secondary" onClick={() => removeLine(i)}>×</button>
              </div>

              {line.mode === "party" && (
                <details style={{ marginTop: "0.5rem" }}>
                  <summary style={{ cursor: "pointer" }}>{t("openItems")}</summary>
                  {line.openItems.map((item, oi) => (
                    <div key={oi} style={{ display: "flex", gap: "0.5rem", marginTop: "0.4rem", flexWrap: "wrap" }}>
                      <input
                        placeholder={t("openItemRef")}
                        value={item.ref}
                        onChange={(e) => updateOpenItem(i, oi, { ref: e.target.value })}
                      />
                      <input type="date" value={item.date} onChange={(e) => updateOpenItem(i, oi, { date: e.target.value })} />
                      <input
                        type="number" step="0.01" placeholder={t("amount")}
                        value={item.amountFc}
                        onChange={(e) => updateOpenItem(i, oi, { amountFc: e.target.value })}
                      />
                      <button type="button" className="secondary" onClick={() => removeOpenItem(i, oi)}>×</button>
                    </div>
                  ))}
                  <button type="button" className="secondary" style={{ marginTop: "0.4rem" }} onClick={() => addOpenItem(i)}>
                    {t("addOpenItem")}
                  </button>
                </details>
              )}
            </div>
          ))}

          <button type="button" className="secondary" onClick={addLine} style={{ marginBottom: "0.75rem" }}>
            {t("addManualLine")}
          </button>

          <p>
            {t("difference")}: <Money amount={String(rawDebit - rawCredit)} /> ({t("balanced")}: {rawDebit === rawCredit ? "✓" : "✗"})
          </p>

          {error && <p className="error-text">{error}</p>}
          <button className="primary" type="submit">{t("createOpeningBalance")}</button>
        </form>
      </div>

      <DataTable<OpeningBalanceEntry>
        endpoint="/opening-balances/"
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
