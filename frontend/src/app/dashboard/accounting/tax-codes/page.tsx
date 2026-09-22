"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { flattenLeafAccounts, type FlatAccountOption } from "@/lib/accounts";
import type {
  AccountTreeNode,
  TaxCode,
  TaxCodeDeductible,
  TaxCodeDirection,
  TaxCodeKind,
} from "@/lib/types";

const KINDS: TaxCodeKind[] = ["standard", "zero_rated", "exempt", "out_of_scope", "reverse_charge"];
const DIRECTIONS: TaxCodeDirection[] = ["output", "input", "both"];
const DEDUCTIBLES: TaxCodeDeductible[] = ["full", "none"];
const KIND_LABEL: Record<TaxCodeKind, string> = {
  standard: "standardKind",
  zero_rated: "zeroRatedKind",
  exempt: "exemptKind",
  out_of_scope: "outOfScopeKind",
  reverse_charge: "reverseChargeKind",
};
const DIRECTION_LABEL: Record<TaxCodeDirection, string> = {
  output: "outputDirection",
  input: "inputDirection",
  both: "bothDirection",
};
const DEDUCTIBLE_LABEL: Record<TaxCodeDeductible, string> = {
  full: "deductibleFull",
  none: "deductibleNone",
};

export default function TaxCodesPage() {
  const { t } = useLocale();
  const [accounts, setAccounts] = useState<FlatAccountOption[]>([]);
  const [editing, setEditing] = useState<TaxCode | null>(null);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [rate, setRate] = useState("0");
  const [kind, setKind] = useState<TaxCodeKind>("standard");
  const [direction, setDirection] = useState<TaxCodeDirection>("output");
  const [deductible, setDeductible] = useState<TaxCodeDeductible>("full");
  const [accountId, setAccountId] = useState("");
  const [countryCode, setCountryCode] = useState("SA");
  const [effectiveFrom, setEffectiveFrom] = useState(() => new Date().toISOString().slice(0, 10));
  const [isActive, setIsActive] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);

  useEffect(() => {
    api.get<AccountTreeNode[]>("/accounts/tree/").then((tree) => setAccounts(flattenLeafAccounts(tree)));
  }, []);

  const startEdit = (row: TaxCode) => {
    setEditing(row);
    setCode(row.code);
    setName(row.name);
    setRate(row.rate);
    setKind(row.kind);
    setDirection(row.direction);
    setDeductible(row.deductible);
    setAccountId(row.account || "");
    setCountryCode(row.country_code);
    setEffectiveFrom(row.effective_from);
    setIsActive(row.is_active);
    setError(null);
  };

  const cancelEdit = () => {
    setEditing(null);
    setCode("");
    setName("");
    setRate("0");
    setKind("standard");
    setDirection("output");
    setDeductible("full");
    setAccountId("");
    setCountryCode("SA");
    setEffectiveFrom(new Date().toISOString().slice(0, 10));
    setIsActive(true);
    setError(null);
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      if (editing) {
        // TaxCodeSerializer.update only allows name/is_active — the
        // rest is frozen once a code exists (matches the 3.16.2 spec).
        await api.patch(`/tax-codes/${editing.id}/`, { name, is_active: isActive });
      } else {
        await api.post("/tax-codes/", {
          code,
          name,
          rate,
          kind,
          direction,
          deductible,
          account: accountId || null,
          country_code: countryCode,
          effective_from: effectiveFrom,
        });
      }
      cancelEdit();
      setRefreshToken((n) => n + 1);
    } catch {
      setError("Could not save this tax code.");
    }
  };

  return (
    <div>
      <h1>{t("taxCodesNav")}</h1>

      <div className="card">
        <h3>{editing ? t("edit") : t("add")}</h3>
        <form onSubmit={onSubmit}>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <div className="form-field">
              <label>{t("code")}</label>
              <input value={code} onChange={(e) => setCode(e.target.value)} required disabled={!!editing} />
            </div>
            <div className="form-field">
              <label>{t("name")}</label>
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </div>
            <div className="form-field">
              <label>{t("rate")}</label>
              <input
                type="number"
                step="0.01"
                value={rate}
                onChange={(e) => setRate(e.target.value)}
                disabled={!!editing}
              />
            </div>
            <label style={{ display: "flex", alignItems: "center", gap: "0.3rem" }}>
              <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
              {t("active")}
            </label>
          </div>

          {!editing && (
            <details open style={{ marginTop: "0.75rem" }}>
              <summary style={{ cursor: "pointer" }}>{t("advanced")}</summary>
              <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
                <div className="form-field">
                  <label>{t("kind")}</label>
                  <select value={kind} onChange={(e) => setKind(e.target.value as TaxCodeKind)}>
                    {KINDS.map((k) => (
                      <option key={k} value={k}>
                        {t(KIND_LABEL[k])}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="form-field">
                  <label>{t("direction")}</label>
                  <select value={direction} onChange={(e) => setDirection(e.target.value as TaxCodeDirection)}>
                    {DIRECTIONS.map((d) => (
                      <option key={d} value={d}>
                        {t(DIRECTION_LABEL[d])}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="form-field">
                  <label>{t("deductible")}</label>
                  <select value={deductible} onChange={(e) => setDeductible(e.target.value as TaxCodeDeductible)}>
                    {DEDUCTIBLES.map((d) => (
                      <option key={d} value={d}>
                        {t(DEDUCTIBLE_LABEL[d])}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="form-field">
                  <label>{t("account")}</label>
                  <select value={accountId} onChange={(e) => setAccountId(e.target.value)}>
                    <option value="">{t("none")}</option>
                    {accounts.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="form-field">
                  <label>{t("countryCode")}</label>
                  <input value={countryCode} onChange={(e) => setCountryCode(e.target.value)} maxLength={2} />
                </div>
                <div className="form-field">
                  <label>{t("effectiveFrom")}</label>
                  <input
                    type="date"
                    value={effectiveFrom}
                    onChange={(e) => setEffectiveFrom(e.target.value)}
                  />
                </div>
              </div>
            </details>
          )}

          {error && <p className="error-text">{error}</p>}
          <button className="primary" type="submit" style={{ marginTop: "0.75rem" }}>
            {editing ? t("saveChanges") : t("add")}
          </button>
          {editing && (
            <button
              type="button"
              className="secondary"
              style={{ marginTop: "0.75rem", marginInlineStart: "0.5rem" }}
              onClick={cancelEdit}
            >
              {t("cancel")}
            </button>
          )}
        </form>
      </div>

      <DataTable<TaxCode>
        endpoint="/tax-codes/"
        refreshToken={refreshToken}
        onEdit={startEdit}
        columns={[
          { key: "code", label: t("code"), sortable: true },
          { key: "name", label: t("name") },
          { key: "rate", label: t("rate") },
          { key: "kind", label: t("kind"), render: (row) => t(KIND_LABEL[row.kind]) },
          { key: "direction", label: t("direction"), render: (row) => t(DIRECTION_LABEL[row.direction]) },
        ]}
      />
    </div>
  );
}
