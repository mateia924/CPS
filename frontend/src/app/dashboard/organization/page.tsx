"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { LegalEntityTree } from "@/components/LegalEntityTree";
import { useLocale } from "@/lib/i18n";
import type { LegalEntity, LegalEntityTreeNode, LegalEntityType, Paginated } from "@/lib/types";

const TYPES: LegalEntityType[] = ["holding", "company", "branch"];

export default function OrganizationPage() {
  const { t } = useLocale();
  const { refreshMe } = useAuth();
  const [tree, setTree] = useState<LegalEntityTreeNode[]>([]);
  const [flat, setFlat] = useState<LegalEntity[]>([]);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [entityType, setEntityType] = useState<LegalEntityType>("branch");
  const [parent, setParent] = useState("");
  const [countryCode, setCountryCode] = useState("SA");
  const [baseCurrency, setBaseCurrency] = useState("SAR");
  const [taxNumber, setTaxNumber] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    const [treeData, flatData] = await Promise.all([
      api.get<LegalEntityTreeNode[]>("/legal-entities/tree/"),
      api.get<Paginated<LegalEntity>>("/legal-entities/"),
    ]);
    setTree(treeData);
    setFlat(flatData.results);
  };

  useEffect(() => {
    load();
  }, []);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await api.post("/legal-entities/", {
        code,
        name,
        entity_type: entityType,
        parent: parent || null,
        country_code: countryCode,
        base_currency: baseCurrency,
        tax_number: taxNumber,
      });
      setCode("");
      setName("");
      setParent("");
      setTaxNumber("");
      await load();
      await refreshMe(); // adding an entity may flip simplified_mode off
    } catch {
      setError("Could not create this entity — check code uniqueness and parent rules.");
    }
  };

  return (
    <div>
      <h1>{t("organization")}</h1>

      <div className="card">
        <LegalEntityTree roots={tree} />
      </div>

      <div className="card">
        <form onSubmit={onSubmit}>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <div className="form-field">
              <label>{t("code")}</label>
              <input value={code} onChange={(e) => setCode(e.target.value)} required />
            </div>
            <div className="form-field">
              <label>{t("name")}</label>
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </div>
            <div className="form-field">
              <label>{t("type")}</label>
              <select value={entityType} onChange={(e) => setEntityType(e.target.value as LegalEntityType)}>
                {TYPES.map((type) => (
                  <option key={type} value={type}>
                    {t(type)}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-field">
              <label>{t("parent")}</label>
              <select value={parent} onChange={(e) => setParent(e.target.value)}>
                <option value="">{t("none")}</option>
                {flat.map((entity) => (
                  <option key={entity.id} value={entity.id}>
                    {entity.code} — {entity.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <details style={{ marginTop: "0.75rem" }}>
            <summary style={{ cursor: "pointer" }}>{t("advanced")}</summary>
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
              <div className="form-field">
                <label>{t("taxNumber")}</label>
                <input value={taxNumber} onChange={(e) => setTaxNumber(e.target.value)} />
              </div>
              <div className="form-field">
                <label>{t("countryCode")}</label>
                <input value={countryCode} onChange={(e) => setCountryCode(e.target.value)} maxLength={2} />
              </div>
              <div className="form-field">
                <label>{t("currency")}</label>
                <input value={baseCurrency} onChange={(e) => setBaseCurrency(e.target.value)} maxLength={3} />
              </div>
            </div>
          </details>

          {error && <p className="error-text">{error}</p>}
          <button className="primary" type="submit" style={{ marginTop: "0.75rem" }}>
            {t("add")}
          </button>
        </form>
      </div>
    </div>
  );
}
