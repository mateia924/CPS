"use client";

import { useLocale } from "@/lib/i18n";
import { FormField } from "@/components/FormField";
import type { StructuredAddressFields } from "@/lib/types";

const KEYS: (keyof StructuredAddressFields)[] = [
  "building_number", "street", "district", "city", "postal_code", "short_address",
];

const LABEL_KEY: Record<keyof StructuredAddressFields, string> = {
  building_number: "buildingNumber",
  street: "street",
  district: "district",
  city: "city",
  postal_code: "postalCode",
  short_address: "shortAddress",
};

export const EMPTY_STRUCTURED_ADDRESS: StructuredAddressFields = {
  building_number: "", street: "", district: "", city: "", postal_code: "", short_address: "",
};

// Sprint 6.8 (F8, decision 20): the collapsed "العنوان المهيكل" section
// shared by every party form (customers/suppliers/employees/
// affiliates) — same StructuredAddressMixin fields already used by
// LegalEntity in settings/company/page.tsx, but that screen has its own
// effective_profile inheritance logic and isn't reused directly here.
export function StructuredAddressFieldset({
  value, onChange, fieldErr = {},
}: {
  value: StructuredAddressFields;
  onChange: (next: StructuredAddressFields) => void;
  fieldErr?: Record<string, string>;
}) {
  const { t } = useLocale();
  return (
    <details style={{ marginTop: "0.75rem" }}>
      <summary style={{ cursor: "pointer" }}>{t("structuredAddressSection")}</summary>
      <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
        {KEYS.map((key) => (
          <FormField name={key} label={t(LABEL_KEY[key])} error={fieldErr[key]} key={key}>
            <input value={value[key]} onChange={(e) => onChange({ ...value, [key]: e.target.value })} />
          </FormField>
        ))}
      </div>
    </details>
  );
}
