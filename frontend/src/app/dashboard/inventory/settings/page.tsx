"use client";

import { useEffect, useState } from "react";
import { api, fieldErrors, generalError } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { FormField } from "@/components/FormField";
import { WarningsBanner } from "@/components/WarningsBanner";
import type { InventorySettingsData, ItemTracking } from "@/lib/types";

export default function InventorySettingsPage() {
  const { t } = useLocale();
  const [settings, setSettings] = useState<InventorySettingsData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});

  useEffect(() => {
    api.get<InventorySettingsData>("/inventory/settings/").then(setSettings);
  }, []);

  if (!settings) return null;

  const patch = async (payload: Partial<InventorySettingsData>) => {
    setError(null);
    setFieldErr({});
    try {
      const updated = await api.patch<InventorySettingsData>("/inventory/settings/", payload);
      setSettings(updated);
    } catch (err) {
      setFieldErr(fieldErrors((err as { body?: unknown }).body));
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  return (
    <div>
      <h1>{t("inventorySettings")}</h1>
      <div className="card">
        <WarningsBanner warnings={error ? [error] : []} variant="error" />
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
          <label style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
            <input
              type="checkbox" checked={settings.allow_negative_stock}
              onChange={(e) => patch({ allow_negative_stock: e.target.checked })}
              /* form-ok: checkbox label-wraps-input, FormField's layout doesn't fit */
            />
            {t("allowNegativeStock")}
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
            <input
              type="checkbox" checked={settings.freeze_warehouse_during_count}
              onChange={(e) => patch({ freeze_warehouse_during_count: e.target.checked })}
              /* form-ok: checkbox label-wraps-input, FormField's layout doesn't fit */
            />
            {t("freezeWarehouseDuringCount")}
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
            <input
              type="checkbox" checked={settings.show_weight_karat_fields}
              onChange={(e) => patch({ show_weight_karat_fields: e.target.checked })}
              /* form-ok: checkbox label-wraps-input, FormField's layout doesn't fit */
            />
            {t("showWeightKaratFields")}
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
            <input
              type="checkbox" checked={settings.units_enabled}
              onChange={(e) => patch({ units_enabled: e.target.checked })}
              /* form-ok: checkbox label-wraps-input, FormField's layout doesn't fit */
            />
            {t("unitsEnabled")}
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
            <input
              type="checkbox" checked={settings.barcode_enabled}
              onChange={(e) => patch({ barcode_enabled: e.target.checked })}
              /* form-ok: checkbox label-wraps-input, FormField's layout doesn't fit */
            />
            {t("barcodeEnabled")}
          </label>
        </div>

        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
          <FormField name="expiry_alert_days" label={t("expiryAlertDays")} error={fieldErr.expiry_alert_days}>
            <input
              type="number" defaultValue={settings.expiry_alert_days}
              onBlur={(e) => Number(e.target.value) !== settings.expiry_alert_days && patch({ expiry_alert_days: Number(e.target.value) })}
            />
          </FormField>
          <FormField name="default_tracking" label={t("defaultTracking")} error={fieldErr.default_tracking}>
            <select value={settings.default_tracking} onChange={(e) => patch({ default_tracking: e.target.value as ItemTracking })}>
              <option value="none">{t("trackingNone")}</option>
              <option value="serial">{t("trackingSerial")}</option>
              <option value="batch">{t("trackingBatch")}</option>
            </select>
          </FormField>
        </div>

      </div>
    </div>
  );
}
