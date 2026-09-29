"use client";

import { useEffect, useState } from "react";
import { api, fieldErrors, generalError } from "@/lib/api";
import { AttachmentPanel } from "@/components/AttachmentPanel";
import { FormField } from "@/components/FormField";
import { WarningsBanner } from "@/components/WarningsBanner";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import type { LegalEntity, Paginated, TenantFeaturesSettings, TenantSettings } from "@/lib/types";

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
          <select value={selectedId} onChange={(e) => setSelectedId(e.target.value)}> {/* form-ok: محدد أي كيان يُعرض للتعديل، ليس حقلًا يُرسَل للـAPI */}
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
            <FormField name="name" label={t("legalName")} required error={fieldErr.name} style={{ flex: 1, minWidth: "220px" }}>
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </FormField>
            <FormField name="tax_number" label={t("taxNumber")} error={fieldErr.tax_number}>
              <input value={taxNumber} onChange={(e) => setTaxNumber(e.target.value)} />
            </FormField>
          </div>

          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "0.5rem" }}>
            {FIELD_KEYS.map((key) => (
              <FormField
                key={key} name={key} label={t(FIELD_LABEL_KEY[key])} error={fieldErr[key]}
                hint={!fields[key] && selected.effective_profile[key] ? t("inheritedFromParent") : undefined}
                style={{ minWidth: "200px" }}
              >
                <input
                  value={fields[key] ?? ""}
                  onChange={(e) => setFields((prev) => ({ ...prev, [key]: e.target.value }))}
                  placeholder={selected.effective_profile[key] || ""}
                />
              </FormField>
            ))}
          </div>

          <br />
          <WarningsBanner warnings={error ? [error] : []} variant="error" />
          {saved && <p style={{ color: "var(--success)" }}>✓</p>}
          <button className="primary" type="submit">{t("saveChanges")}</button>
        </form>
      </div>

      <AttachmentPanel targetType="legal_entity" targetId={selected.id} />

      <TenantPolicyCard />

      <AdvancedSettingsCard entities={entities} />
    </div>
  );
}

// Sprint 6.5.14: الإعدادات ← الشركة ← متقدم — «الكيان الافتراضي
// للمستندات» (Tenant.default_legal_entity). Owner-only edit, same as
// TenantPolicyCard above but its own card/endpoint since the field
// lives on Tenant, not TenantFeatures — visible read-only to non-
// Owners too (GET has no permission gate server-side).
function AdvancedSettingsCard({ entities }: { entities: LegalEntity[] }) {
  const { t } = useLocale();
  const { me } = useAuth();
  const isOwner = !!me && me.roles.includes("Owner");
  const [settings, setSettings] = useState<TenantSettings | null>(null);
  const [defaultEntityId, setDefaultEntityId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.get<TenantSettings>("/tenant-settings/").then((data) => {
      setSettings(data);
      setDefaultEntityId(data.default_legal_entity || "");
    });
  }, []);

  if (!settings) return null;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSaved(false);
    try {
      const updated = await api.patch<TenantSettings>("/tenant-settings/", {
        default_legal_entity: defaultEntityId || null,
      });
      setSettings(updated);
      setSaved(true);
    } catch (err) {
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  return (
    <div className="card">
      <h3>{t("advancedSettingsSection")}</h3>
      <form onSubmit={onSubmit}>
        <FormField name="default_legal_entity" label={t("defaultLegalEntity")} hint={t("defaultLegalEntityHint")} style={{ maxWidth: "320px" }}>
          <select value={defaultEntityId} onChange={(e) => setDefaultEntityId(e.target.value)} disabled={!isOwner}>
            <option value="">{t("noSelection")}</option>
            {entities.map((entity) => (
              <option key={entity.id} value={entity.id}>{entity.code} — {entity.name}</option>
            ))}
          </select>
        </FormField>

        {isOwner && (
          <>
            <br />
            <WarningsBanner warnings={error ? [error] : []} variant="error" />
            {saved && <p style={{ color: "var(--success)" }}>✓</p>}
            <button className="primary" type="submit">{t("saveChanges")}</button>
          </>
        )}
      </form>
    </div>
  );
}

// Sprint 6.8 (decisions 16/19): tenant-wide policy switches — not tied to
// any single legal entity, so this is its own card with its own
// load/save cycle against /tenant-features/ rather than reusing the
// legal-entity form above it.
function TenantPolicyCard() {
  const { t } = useLocale();
  const [features, setFeatures] = useState<TenantFeaturesSettings | null>(null);
  const [creditLimitMode, setCreditLimitMode] = useState<"warn" | "block">("warn");
  const [costCenterRequired, setCostCenterRequired] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.get<TenantFeaturesSettings>("/tenant-features/").then((data) => {
      setFeatures(data);
      setCreditLimitMode(data.credit_limit_mode);
      setCostCenterRequired(data.cost_center_required);
    });
  }, []);

  if (!features) return null;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSaved(false);
    try {
      const updated = await api.patch<TenantFeaturesSettings>("/tenant-features/", {
        credit_limit_mode: creditLimitMode,
        cost_center_required: costCenterRequired,
      });
      setFeatures(updated);
      setSaved(true);
    } catch (err) {
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  return (
    <div className="card">
      <h3>{t("tenantPolicySettings")}</h3>
      <form onSubmit={onSubmit}>
        <FormField name="credit_limit_mode" label={t("creditLimitMode")} style={{ maxWidth: "320px" }}>
          <select value={creditLimitMode} onChange={(e) => setCreditLimitMode(e.target.value as "warn" | "block")}>
            <option value="warn">{t("creditLimitModeWarn")}</option>
            <option value="block">{t("creditLimitModeBlock")}</option>
          </select>
        </FormField>

        <div className="form-field" style={{ marginTop: "0.5rem" }}>
          <label>
            <input type="checkbox" checked={costCenterRequired} onChange={(e) => setCostCenterRequired(e.target.checked)} /* form-ok: مربع اختيار سياسة تشغيلية، لا يُرجع خطأ حقل من الـAPI */ />{" "}
            {t("costCenterRequired")}
          </label>
        </div>

        <br />
        <WarningsBanner warnings={error ? [error] : []} variant="error" />
        {saved && <p style={{ color: "var(--success)" }}>✓</p>}
        <button className="primary" type="submit">{t("saveChanges")}</button>
      </form>
    </div>
  );
}
