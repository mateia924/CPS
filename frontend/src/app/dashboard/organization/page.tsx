"use client";

import { useEffect, useState } from "react";
import { api, fieldErrors, generalError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { LegalEntityTree } from "@/components/LegalEntityTree";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { WarningsBanner } from "@/components/WarningsBanner";
import { useLocale } from "@/lib/i18n";
import type { LegalEntity, LegalEntityTreeNode, LegalEntityType, Paginated } from "@/lib/types";

const TYPES: LegalEntityType[] = ["holding", "company", "branch"];

export default function OrganizationPage() {
  const { t } = useLocale();
  const { me, refreshMe } = useAuth();
  const [tree, setTree] = useState<LegalEntityTreeNode[]>([]);
  const [simplifiedModeEndedWarning, setSimplifiedModeEndedWarning] = useState(false);
  const [flat, setFlat] = useState<LegalEntity[]>([]);
  const [editing, setEditing] = useState<LegalEntity | null>(null);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [entityType, setEntityType] = useState<LegalEntityType>("branch");
  const [parent, setParent] = useState("");
  const [countryCode, setCountryCode] = useState("SA");
  const [baseCurrency, setBaseCurrency] = useState("SAR");
  const [taxNumber, setTaxNumber] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});
  const [refreshToken, setRefreshToken] = useState(0);

  const loadTreeAndParents = async () => {
    const [treeData, flatData] = await Promise.all([
      api.get<LegalEntityTreeNode[]>("/legal-entities/tree/"),
      api.get<Paginated<LegalEntity>>("/legal-entities/"),
    ]);
    setTree(treeData);
    setFlat(flatData.results);
  };

  useEffect(() => {
    loadTreeAndParents();
  }, [refreshToken]);

  const startEdit = (entity: LegalEntity) => {
    setEditing(entity);
    setCode(entity.code);
    setName(entity.name);
    setEntityType(entity.entity_type);
    setParent(entity.parent || "");
    setCountryCode(entity.country_code);
    setBaseCurrency(entity.base_currency);
    setTaxNumber(entity.tax_number);
  };

  const cancelEdit = () => {
    setEditing(null);
    setCode("");
    setName("");
    setEntityType("branch");
    setParent("");
    setCountryCode("SA");
    setBaseCurrency("SAR");
    setTaxNumber("");
    setError(null);
    setFieldErr({});
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setFieldErr({});
    const payload = {
      code,
      name,
      entity_type: entityType,
      parent: parent || null,
      country_code: countryCode,
      base_currency: baseCurrency,
      tax_number: taxNumber,
    };
    const wasSimplified = !!me?.simplified_mode;
    try {
      if (editing) {
        await api.patch(`/legal-entities/${editing.id}/`, payload);
      } else {
        await api.post("/legal-entities/", payload);
      }
      cancelEdit();
      setRefreshToken((n) => n + 1);
      const updatedMe = await refreshMe(); // adding/editing an entity may flip simplified_mode
      // Sprint 6.5.18 (UAT item 7): adding the tenant's second branch
      // ends simplified mode — from here on, entity pickers and entity
      // codes-in-numbering start appearing everywhere; a one-time
      // warning at the exact moment this flips is the only place an
      // owner would otherwise learn this.
      if (wasSimplified && updatedMe && !updatedMe.simplified_mode) {
        setSimplifiedModeEndedWarning(true);
      }
    } catch (err) {
      setFieldErr(fieldErrors((err as { body?: unknown }).body));
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  return (
    <div>
      <h1>{t("organization")}</h1>

      <WarningsBanner warnings={simplifiedModeEndedWarning ? [t("simplifiedModeEndedWarning")] : []} />

      <div className="card">
        <LegalEntityTree roots={tree} />
      </div>

      <div className="card">
        <form onSubmit={onSubmit}>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <FormField name="code" required error={fieldErr.code}>
              <input value={code} onChange={(e) => setCode(e.target.value)} required />
            </FormField>
            <FormField name="name" required error={fieldErr.name}>
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </FormField>
            <FormField name="entity_type" label={t("type")} error={fieldErr.entity_type}>
              <select value={entityType} onChange={(e) => setEntityType(e.target.value as LegalEntityType)}>
                {TYPES.map((type) => (
                  <option key={type} value={type}>
                    {t(type)}
                  </option>
                ))}
              </select>
            </FormField>
            <FormField name="parent" error={fieldErr.parent}>
              <select value={parent} onChange={(e) => setParent(e.target.value)}>
                <option value="">{t("none")}</option>
                {flat
                  .filter((entity) => entity.id !== editing?.id)
                  .map((entity) => (
                    <option key={entity.id} value={entity.id}>
                      {entity.code} — {entity.name}
                    </option>
                  ))}
              </select>
            </FormField>
          </div>

          <details style={{ marginTop: "0.75rem" }}>
            <summary style={{ cursor: "pointer" }}>{t("advanced")}</summary>
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
              <FormField name="tax_number" error={fieldErr.tax_number}>
                <input value={taxNumber} onChange={(e) => setTaxNumber(e.target.value)} />
              </FormField>
              <FormField name="country_code" error={fieldErr.country_code}>
                <input value={countryCode} onChange={(e) => setCountryCode(e.target.value)} maxLength={2} />
              </FormField>
              <FormField name="base_currency" label={t("currency")} error={fieldErr.base_currency}>
                <input value={baseCurrency} onChange={(e) => setBaseCurrency(e.target.value)} maxLength={3} />
              </FormField>
            </div>
          </details>

          <WarningsBanner warnings={error ? [error] : []} variant="error" />
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

      <DataTable<LegalEntity>
        endpoint="/legal-entities/"
        refreshToken={refreshToken}
        onEdit={startEdit}
        columns={[
          { key: "code", label: t("code"), sortable: true },
          { key: "name", label: t("name"), sortable: true },
          { key: "entity_type", label: t("type"), render: (row) => t(row.entity_type) },
        ]}
      />
    </div>
  );
}
