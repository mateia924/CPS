"use client";

import { useEffect, useState } from "react";
import { api, fieldErrors, generalError } from "@/lib/api";
import { AttachmentPanel } from "@/components/AttachmentPanel";
import { useLocale } from "@/lib/i18n";
import type { LegalEntity, Paginated } from "@/lib/types";

const FIELD_KEYS = [
  "commercial_registration", "building_number", "street", "district",
  "city", "postal_code", "short_address", "phone", "email",
] as const;

const FIELD_LABEL_KEY: Record<(typeof FIELD_KEYS)[number], string> = {
  commercial_registration: "commercialRegistration",
  building_number: "buildingNumber",
  street: "street",
  district: "district",
  city: "city",
  postal_code: "postalCode",
  short_address: "shortAddress",
  phone: "phone",
  email: "email",
};

// Sprint 5.6 (block 5.6): "شاشة الشركة" — unlike /dashboard/organization
// (the multi-entity tree, hidden entirely for a simplified-mode single-
// branch tenant), every tenant needs somewhere to set its legal name,
// tax number, CR and structured address, so this screen is always
// visible and defaults to editing the tenant's own single entity when
// there's only one.
export default function CompanySettingsPage() {
  const { t } = useLocale();
  const [entities, setEntities] = useState<LegalEntity[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [name, setName] = useState("");
  const [taxNumber, setTaxNumber] = useState("");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState(false);

  const load = async () => {
    const data = await api.get<Paginated<LegalEntity>>("/legal-entities/");
    setEntities(data.results);
    if (data.results.length > 0 && !selectedId) {
      setSelectedId(data.results[0].id);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selected = entities.find((entity) => entity.id === selectedId) || null;

  useEffect(() => {
    if (!selected) return;
    setName(selected.name);
    setTaxNumber(selected.tax_number);
    const next: Record<string, string> = {};
    for (const key of FIELD_KEYS) next[key] = selected[key];
    setFields(next);
    setSaved(false);
  }, [selected]);

  if (!selected) return null;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setFieldErr({});
    setSaved(false);
    try {
      const updated = await api.patch<LegalEntity>(`/legal-entities/${selected.id}/`, {
        name, tax_number: taxNumber, ...fields,
      });
      setEntities((prev) => prev.map((entity) => (entity.id === updated.id ? updated : entity)));
      setSaved(true);
    } catch (err) {
      setFieldErr(fieldErrors((err as { body?: unknown }).body));
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  return (
    <div>
      <h1>{t("companySettingsNav")}</h1>

      {entities.length > 1 && (
        <div className="form-field" style={{ maxWidth: "320px", marginBottom: "1rem" }}>
          <label>{t("legalEntity")}</label>
          <select value={selectedId} onChange={(e) => setSelectedId(e.target.value)}>
            {entities.map((entity) => (
              <option key={entity.id} value={entity.id}>{entity.code} — {entity.name}</option>
            ))}
          </select>
        </div>
      )}

      <div className="card">
        <h3>{t("companySettings")}</h3>
        <form onSubmit={onSubmit}>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <div className="form-field" style={{ flex: 1, minWidth: "220px" }}>
              <label>{t("legalName")}</label>
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </div>
            <div className="form-field">
              <label>{t("taxNumber")}</label>
              <input value={taxNumber} onChange={(e) => setTaxNumber(e.target.value)} />
              {fieldErr.tax_number && <p className="error-text">{fieldErr.tax_number}</p>}
            </div>
          </div>

          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "0.5rem" }}>
            {FIELD_KEYS.map((key) => (
              <div className="form-field" key={key} style={{ minWidth: "200px" }}>
                <label>
                  {t(FIELD_LABEL_KEY[key])}
                  {!fields[key] && selected.effective_profile[key] && (
                    <span style={{ color: "var(--muted)", fontSize: "0.75rem" }}> {t("inheritedFromParent")}</span>
                  )}
                </label>
                <input
                  value={fields[key] ?? ""}
                  onChange={(e) => setFields((prev) => ({ ...prev, [key]: e.target.value }))}
                  placeholder={selected.effective_profile[key] || ""}
                />
                {fieldErr[key] && <p className="error-text">{fieldErr[key]}</p>}
              </div>
            ))}
          </div>

          <br />
          {error && <p className="error-text">{error}</p>}
          {saved && <p style={{ color: "#1f9d55" }}>✓</p>}
          <button className="primary" type="submit">{t("saveChanges")}</button>
        </form>
      </div>

      <AttachmentPanel targetType="legal_entity" targetId={selected.id} />
    </div>
  );
}
