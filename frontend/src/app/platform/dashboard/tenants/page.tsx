"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { platformApi } from "@/lib/api";
import type { Paginated, Plan, PlatformTenant, TenantStatus } from "@/lib/types";

const STATUS_LABEL_KEY: Record<TenantStatus, string> = {
  trial: "trial",
  active: "active",
  past_due: "pastDue",
  suspended: "suspended",
  archived: "archived",
};

export default function PlatformTenantsPage() {
  const { t } = useLocale();
  const router = useRouter();
  const [plans, setPlans] = useState<Plan[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [planFilter, setPlanFilter] = useState("");

  useEffect(() => {
    platformApi.get<Paginated<Plan>>("/platform/plans/").then((data) => setPlans(data.results));
  }, []);

  return (
    <div>
      <h1>{t("tenants")}</h1>

      <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1rem" }}>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}> {/* form-ok: GET-only filter */}
          <option value="">{t("status")}: {t("all")}</option>
          {Object.entries(STATUS_LABEL_KEY).map(([value, labelKey]) => (
            <option key={value} value={value}>
              {t(labelKey)}
            </option>
          ))}
        </select>
        <select value={planFilter} onChange={(e) => setPlanFilter(e.target.value)}> {/* form-ok: GET-only filter */}
          <option value="">{t("plan")}: {t("all")}</option>
          {plans.map((plan) => (
            <option key={plan.code} value={plan.code}>
              {plan.name}
            </option>
          ))}
        </select>
      </div>

      <DataTable<PlatformTenant>
        endpoint="/platform/tenants/"
        api={platformApi}
        hasActiveToggle={false}
        extraParams={{ status: statusFilter, plan: planFilter }}
        onEdit={(row) => router.push(`/platform/dashboard/tenants/${row.id}`)}
        columns={[
          { key: "name", label: t("name") },
          { key: "subdomain", label: t("subdomain") },
          { key: "plan_code", label: t("plan") },
          { key: "status", label: t("status"), render: (row) => t(STATUS_LABEL_KEY[row.status]) },
          { key: "user_count", label: t("users") },
          { key: "invoice_count", label: t("invoices") },
          {
            key: "last_activity",
            label: t("lastActivity"),
            render: (row) => (row.last_activity ? new Date(row.last_activity).toLocaleString() : "—"),
          },
          {
            key: "created_at",
            label: t("createdAt"),
            render: (row) => new Date(row.created_at).toLocaleDateString(),
          },
        ]}
      />
    </div>
  );
}
