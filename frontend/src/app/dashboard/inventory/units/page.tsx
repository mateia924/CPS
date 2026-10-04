"use client";

import { useState } from "react";
import { api, fieldErrors, generalError } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { WarningsBanner } from "@/components/WarningsBanner";
import type { UnitOfMeasure } from "@/lib/types";

export default function UnitsOfMeasurePage() {
  const { t } = useLocale();
  const [editing, setEditing] = useState<UnitOfMeasure | null>(null);
  const [code, setCode] = useState("");
  const [nameAr, setNameAr] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});
  const [refreshToken, setRefreshToken] = useState(0);

  const startEdit = (uom: UnitOfMeasure) => {
    setEditing(uom);
    setCode(uom.code);
    setNameAr(uom.name_ar);
    setError(null);
    setFieldErr({});
  };

  const cancelEdit = () => {
    setEditing(null);
    setCode("");
    setNameAr("");
    setError(null);
    setFieldErr({});
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setFieldErr({});
    const payload = { code, name_ar: nameAr };
    try {
      if (editing) {
        await api.patch(`/inventory/units/${editing.id}/`, payload);
      } else {
        await api.post("/inventory/units/", payload);
      }
      cancelEdit();
      setRefreshToken((n) => n + 1);
    } catch (err) {
      setFieldErr(fieldErrors((err as { body?: unknown }).body));
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  return (
    <div>
      <h1>{t("unitsOfMeasure")}</h1>
      <div className="card">
        <h3>{editing ? t("edit") : t("add")}</h3>
        <form onSubmit={onSubmit} style={{ display: "flex", gap: "0.75rem", alignItems: "end", flexWrap: "wrap" }}>
          <FormField name="code" label={t("code")} required error={fieldErr.code}>
            <input value={code} onChange={(e) => setCode(e.target.value)} required />
          </FormField>
          <FormField name="name_ar" label={t("name")} required error={fieldErr.name_ar}>
            <input value={nameAr} onChange={(e) => setNameAr(e.target.value)} required />
          </FormField>
          <button className="primary" type="submit">
            {editing ? t("saveChanges") : t("add")}
          </button>
          {editing && (
            <button type="button" className="secondary" onClick={cancelEdit}>
              {t("cancel")}
            </button>
          )}
        </form>
        <WarningsBanner warnings={error ? [error] : []} variant="error" />
      </div>

      <DataTable<UnitOfMeasure>
        endpoint="/inventory/units/"
        refreshToken={refreshToken}
        onEdit={startEdit}
        hasActiveToggle
        columns={[
          { key: "code", label: t("code"), sortable: true },
          { key: "name_ar", label: t("name"), sortable: true },
        ]}
      />
    </div>
  );
}
