"use client";

import { useEffect, useState } from "react";
import { api, fieldErrors, generalError } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { WarningsBanner } from "@/components/WarningsBanner";
import type { PurchaseSettingsData, WithholdingTaxCode } from "@/lib/types";

// Sprint 8.0: R-8.5's match tolerance and the GRNI policy, plus the
// tenant's withholding codes (D6). The codes come from the country's
// compliance table and stay marked as examples until the owner approves
// them with a tax advisor (S2) — the badge says so on every such row.
// Read-only here: approving/editing a code is block 8.3's screen.
export default function PurchaseSettingsPage() {
  const { t } = useLocale();
  const [settings, setSettings] = useState<PurchaseSettingsData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});

  useEffect(() => {
    api.get<PurchaseSettingsData>("/purchasing/settings/").then(setSettings);
  }, []);

  if (!settings) return null;

  const patch = async (payload: Partial<PurchaseSettingsData>) => {
    setError(null);
    setFieldErr({});
    try {
      const updated = await api.patch<PurchaseSettingsData>("/purchasing/settings/", payload);
      setSettings(updated);
    } catch (err) {
      setFieldErr(fieldErrors((err as { body?: unknown }).body));
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  return (
    <div>
      <h1>{t("purchaseSettings")}</h1>
      <div className="card">
        <h3 style={{ marginTop: 0 }}>{t("matchTolerance")}</h3>
        <p style={{ marginTop: 0, color: "var(--muted)" }}>{t("matchToleranceHint")}</p>
        <WarningsBanner warnings={error ? [error] : []} variant="error" />
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
          <FormField name="match_tolerance_pct" label={t("matchTolerancePct")} error={fieldErr.match_tolerance_pct}>
            <input
              type="number" step="0.01" min="0" max="100" defaultValue={settings.match_tolerance_pct}
              onBlur={(e) => e.target.value !== settings.match_tolerance_pct && patch({ match_tolerance_pct: e.target.value })}
            />
          </FormField>
          <FormField name="match_tolerance_amount" label={t("matchToleranceAmount")} error={fieldErr.match_tolerance_amount}>
            <input
              type="number" step="0.01" min="0" defaultValue={settings.match_tolerance_amount}
              onBlur={(e) => e.target.value !== settings.match_tolerance_amount && patch({ match_tolerance_amount: e.target.value })}
            />
          </FormField>
          <FormField name="default_grni_policy" label={t("grniPolicy")} error={fieldErr.default_grni_policy}>
            <select value={settings.default_grni_policy} onChange={(e) => patch({ default_grni_policy: e.target.value as PurchaseSettingsData["default_grni_policy"] })}>
              <option value="prorate">{t("grniPolicyProrate")}</option>
            </select>
          </FormField>
        </div>
      </div>

      <div className="card">
        <h3 style={{ marginTop: 0 }}>{t("withholdingCodes")}</h3>
        <DataTable<WithholdingTaxCode>
          endpoint="/purchasing/withholding-codes/"
          hasActiveToggle={false}
          emptyMessage={t("withholdingCodesEmpty")}
          columns={[
            { key: "country", label: t("countryCode") },
            { key: "code", label: t("code") },
            {
              key: "name_ar",
              label: t("name"),
              render: (row) => (
                <>
                  {row.name_ar}
                  {row.is_example && (
                    <>
                      {" "}
                      <span
                        style={{
                          display: "inline-block",
                          padding: "0.15rem 0.6rem",
                          borderRadius: "var(--radius-pill)",
                          fontSize: "0.8rem",
                          fontWeight: 600,
                          color: "var(--warning)",
                          background: "var(--warning-bg)",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {t("withholdingExampleBadge")}
                      </span>
                    </>
                  )}
                </>
              ),
            },
            { key: "rate", label: t("rate") },
            { key: "base", label: t("withholdingBase"), render: (row) => t(row.base === "net" ? "withholdingBaseNet" : "withholdingBaseGross") },
            {
              key: "applies_to",
              label: t("withholdingAppliesTo"),
              render: (row) =>
                t(
                  row.applies_to === "resident"
                    ? "withholdingResident"
                    : row.applies_to === "non_resident"
                      ? "withholdingNonResident"
                      : "withholdingBoth",
                ),
            },
          ]}
        />
      </div>
    </div>
  );
}
