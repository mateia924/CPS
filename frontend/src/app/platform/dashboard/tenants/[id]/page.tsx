"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useLocale } from "@/lib/i18n";
import { ApiError, generalError, platformApi } from "@/lib/api";
import type { Paginated, Plan, PlatformTenant, TenantStatus } from "@/lib/types";

const STATUS_LABEL_KEY: Record<TenantStatus, string> = {
  trial: "trial",
  active: "active",
  past_due: "pastDue",
  suspended: "suspended",
  archived: "archived",
};

const FALLBACK_ERROR: Record<"ar" | "en", string> = {
  ar: "حدث خطأ غير متوقع. حاول مرة أخرى.",
  en: "Something went wrong. Please try again.",
};

export default function PlatformTenantDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { t, locale } = useLocale();

  const [tenant, setTenant] = useState<PlatformTenant | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [selectedPlan, setSelectedPlan] = useState("");
  const [trialEndsAt, setTrialEndsAt] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    const [tenantData, plansData] = await Promise.all([
      platformApi.get<PlatformTenant>(`/platform/tenants/${id}/`),
      platformApi.get<Paginated<Plan>>("/platform/plans/"),
    ]);
    setTenant(tenantData);
    setSelectedPlan(tenantData.plan_code);
    setPlans(plansData.results);
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const handleError = (err: unknown) => {
    if (err instanceof ApiError) {
      setError(generalError(err.body, FALLBACK_ERROR[locale]));
    } else {
      setError(FALLBACK_ERROR[locale]);
    }
  };

  const onChangePlan = async () => {
    if (!tenant) return;
    const plan = plans.find((p) => p.code === selectedPlan);
    if (!plan) return;
    setError(null);
    setSaving(true);
    try {
      const updated = await platformApi.post<PlatformTenant>(
        `/platform/tenants/${tenant.id}/change_plan/`,
        { plan: plan.id }
      );
      setTenant(updated);
    } catch (err) {
      handleError(err);
    } finally {
      setSaving(false);
    }
  };

  const onExtendTrial = async () => {
    if (!tenant || !trialEndsAt) return;
    setError(null);
    setSaving(true);
    try {
      const updated = await platformApi.post<PlatformTenant>(
        `/platform/tenants/${tenant.id}/extend_trial/`,
        { trial_ends_at: new Date(trialEndsAt).toISOString() }
      );
      setTenant(updated);
    } catch (err) {
      handleError(err);
    } finally {
      setSaving(false);
    }
  };

  const onSuspendOrActivate = async (action: "suspend" | "activate") => {
    if (!tenant) return;
    if (reason.trim().length < 3) {
      setError(t("reasonRequired"));
      return;
    }
    setError(null);
    setSaving(true);
    try {
      const updated = await platformApi.post<PlatformTenant>(
        `/platform/tenants/${tenant.id}/${action}/`,
        { reason }
      );
      setTenant(updated);
      setReason("");
    } catch (err) {
      handleError(err);
    } finally {
      setSaving(false);
    }
  };

  if (!tenant) return null;

  return (
    <div>
      <button className="secondary" onClick={() => router.push("/platform/dashboard/tenants")}>
        ← {t("back")}
      </button>

      <h1 style={{ marginTop: "1rem" }}>{tenant.name}</h1>
      <p style={{ color: "var(--muted)" }}>
        {tenant.subdomain} — {t(STATUS_LABEL_KEY[tenant.status])}
      </p>

      {error && <p className="error-text">{error}</p>}

      <div className="card">
        <h3>{t("changePlan")}</h3>
        <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
          <select value={selectedPlan} onChange={(e) => setSelectedPlan(e.target.value)}>
            {plans.map((plan) => (
              <option key={plan.code} value={plan.code}>
                {plan.name}
              </option>
            ))}
          </select>
          <button className="primary" onClick={onChangePlan} disabled={saving}>
            {t("save")}
          </button>
        </div>
      </div>

      <div className="card">
        <h3>{t("extendTrial")}</h3>
        <p style={{ color: "var(--muted)", fontSize: "0.9rem" }}>
          {t("trialEndsAt")}: {tenant.trial_ends_at ? new Date(tenant.trial_ends_at).toLocaleString() : "—"}
        </p>
        <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
          <input
            type="datetime-local"
            value={trialEndsAt}
            onChange={(e) => setTrialEndsAt(e.target.value)}
          />
          <button className="primary" onClick={onExtendTrial} disabled={saving || !trialEndsAt}>
            {t("save")}
          </button>
        </div>
      </div>

      <div className="card">
        <h3>{t("suspend")} / {t("reactivateTenant")}</h3>
        <div className="form-field">
          <label>{t("reason")}</label>
          <input value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
        <button
          className="secondary"
          onClick={() => onSuspendOrActivate("suspend")}
          disabled={saving || tenant.status === "suspended"}
        >
          {t("suspend")}
        </button>
        <button
          className="secondary"
          style={{ marginInlineStart: "0.5rem" }}
          onClick={() => onSuspendOrActivate("activate")}
          disabled={saving || tenant.status === "active"}
        >
          {t("reactivateTenant")}
        </button>
      </div>

      <div className="card">
        <h3>{t("details")}</h3>
        <p>{t("users")}: {tenant.user_count}</p>
        <p>{t("invoices")}: {tenant.invoice_count}</p>
        <p>
          {t("lastActivity")}:{" "}
          {tenant.last_activity ? new Date(tenant.last_activity).toLocaleString() : "—"}
        </p>
        <p>{t("createdAt")}: {new Date(tenant.created_at).toLocaleDateString()}</p>
      </div>
    </div>
  );
}
