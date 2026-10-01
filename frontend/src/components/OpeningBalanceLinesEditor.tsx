"use client";

// Sprint 6.3: the opening-balance line-editing form, extracted in
// sprint 6.6.3d so the create screen (always a fresh set of lines) and
// the detail screen's own "edit lines while still a draft" section
// (UAT 6 finding A — a draft had no way to fix an unbalanced line set
// at all) share the exact same fields/behavior instead of two forms
// quietly drifting apart over time.

import { FormField } from "@/components/FormField";
import { useLocale } from "@/lib/i18n";
import type { AccountTreeNode, CostCenter, Party, PartyRoleType } from "@/lib/types";

export interface OpenItemDraft {
  ref: string;
  date: string;
  amountFc: string;
}

export interface LineDraft {
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

export const EMPTY_LINE: LineDraft = {
  mode: "account", account: "", party: "", partyRole: "", costCenter: "",
  currency: "", exchangeRate: "", debitFc: "", creditFc: "", openItems: [], notes: "",
};

export const PARTY_ROLES: { value: PartyRoleType; labelKey: string }[] = [
  { value: "customer", labelKey: "customerRole" },
  { value: "supplier", labelKey: "supplierRole" },
  { value: "employee", labelKey: "employeeRole" },
  { value: "affiliate", labelKey: "affiliateRole" },
];

/** Decision 6: only balance-sheet leaf accounts belong in the picker —
 * the backend rejects revenue/expense lines with 400, this just keeps
 * the dropdown from offering them in the first place. */
export function balanceSheetLeafAccounts(nodes: AccountTreeNode[]): AccountTreeNode[] {
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

/** Same request-shape transform the create screen always used — the
 * detail screen's own "save lines" button (PATCH .../lines/) needs the
 * identical shape the create screen's own POST already sends. */
export function linesToPayload(lines: LineDraft[]) {
  return lines
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
    }));
}

interface OpeningBalanceLinesEditorProps {
  lines: LineDraft[];
  onChange: (lines: LineDraft[]) => void;
  accounts: AccountTreeNode[];
  parties: Party[];
  costCenters: CostCenter[];
  showCostCenterUI: boolean;
}

export function OpeningBalanceLinesEditor({
  lines, onChange, accounts, parties, costCenters, showCostCenterUI,
}: OpeningBalanceLinesEditorProps) {
  const { t } = useLocale();
  const leafAccounts = balanceSheetLeafAccounts(accounts);

  const addLine = () => onChange([...lines, { ...EMPTY_LINE }]);
  const updateLine = (index: number, patch: Partial<LineDraft>) => {
    onChange(lines.map((line, i) => (i === index ? { ...line, ...patch } : line)));
  };
  const removeLine = (index: number) => onChange(lines.filter((_, i) => i !== index));

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

  return (
    <>
      {lines.map((line, i) => (
        <div key={i} className="card" style={{ background: "var(--surface-2, transparent)" }}>
          <div style={{ display: "flex", gap: "0.75rem", alignItems: "end", flexWrap: "wrap" }}>
            <FormField name="mode" label={`${t("lineByAccount")} / ${t("lineByParty")}`}>
              <select
                value={line.mode}
                onChange={(e) => updateLine(i, { mode: e.target.value as "account" | "party" })}
              >
                <option value="account">{t("lineByAccount")}</option>
                <option value="party">{t("lineByParty")}</option>
              </select>
            </FormField>

            {line.mode === "account" ? (
              <FormField name="account" style={{ flex: 1, minWidth: "220px" }}>
                <select value={line.account} onChange={(e) => updateLine(i, { account: e.target.value })} required>
                  <option value="" disabled>—</option>
                  {leafAccounts.map((a) => (
                    <option key={a.id} value={a.id}>{a.code} — {a.name}</option>
                  ))}
                </select>
              </FormField>
            ) : (
              <>
                <FormField name="party" style={{ flex: 1, minWidth: "180px" }}>
                  <select value={line.party} onChange={(e) => updateLine(i, { party: e.target.value })} required>
                    <option value="" disabled>—</option>
                    {parties.map((p) => (
                      <option key={p.id} value={p.id}>{p.code} — {p.name}</option>
                    ))}
                  </select>
                </FormField>
                <FormField name="party_role" style={{ minWidth: "160px" }}>
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
                </FormField>
              </>
            )}

            {showCostCenterUI && (
              <FormField name="cost_center" style={{ minWidth: "160px" }}>
                <select value={line.costCenter} onChange={(e) => updateLine(i, { costCenter: e.target.value })}>
                  <option value="">{t("none")}</option>
                  {costCenters.map((cc) => (
                    <option key={cc.id} value={cc.id}>{cc.code} — {cc.name}</option>
                  ))}
                </select>
              </FormField>
            )}

            <FormField name="currency" style={{ width: "90px" }}>
              <input value={line.currency} onChange={(e) => updateLine(i, { currency: e.target.value })} maxLength={3} />
            </FormField>
            <FormField name="debit_fc" style={{ width: "130px" }}>
              <input type="number" step="0.01" value={line.debitFc} onChange={(e) => updateLine(i, { debitFc: e.target.value })} />
            </FormField>
            <FormField name="credit_fc" style={{ width: "130px" }}>
              <input type="number" step="0.01" value={line.creditFc} onChange={(e) => updateLine(i, { creditFc: e.target.value })} />
            </FormField>
            <button type="button" className="secondary" onClick={() => removeLine(i)}>×</button>
          </div>

          {line.mode === "party" && (
            <details style={{ marginTop: "0.5rem" }}>
              <summary style={{ cursor: "pointer" }}>{t("openItems")}</summary>
              {line.openItems.map((item, oi) => (
                <div key={oi} style={{ display: "flex", gap: "0.5rem", marginTop: "0.4rem", flexWrap: "wrap" }}>
                  {/* form-ok: صف بند مفتوح فرعي (رابع مستوى تعشيش) — لا تخطئة حقل من الـAPI على هذا العمق، placeholder بدل تسمية لضيق المساحة */}
                  <input
                    placeholder={t("openItemRef")}
                    value={item.ref}
                    onChange={(e) => updateOpenItem(i, oi, { ref: e.target.value })}
                  />
                  <input type="date" value={item.date} onChange={(e) => updateOpenItem(i, oi, { date: e.target.value })} /> {/* form-ok: بند مفتوح فرعي، لا تخطئة حقل بهذا العمق */}
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
    </>
  );
}
