"use client";

import { useState } from "react";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { platformApi } from "@/lib/api";
import type { AuditLogEntry } from "@/lib/types";

export default function PlatformAuditLogPage() {
  const { t } = useLocale();
  const [actorType, setActorType] = useState("");
  const [action, setAction] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [selected, setSelected] = useState<AuditLogEntry | null>(null);

  return (
    <div>
      <h1>{t("auditLog")}</h1>

      <div className="card">
        <h3>{t("filters")}</h3>
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
          <select value={actorType} onChange={(e) => setActorType(e.target.value)}>
            <option value="">{t("actorType")}: {t("all")}</option>
            <option value="platform">{t("platform")}</option>
            <option value="tenant_user">{t("tenantUser")}</option>
          </select>
          <input
            placeholder={t("action")}
            value={action}
            onChange={(e) => setAction(e.target.value)}
            style={{ padding: "0.5rem 0.7rem", border: "1px solid var(--border)", borderRadius: "8px" }}
          />
          <input
            placeholder={`${t("tenants")} ID`}
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
            style={{ padding: "0.5rem 0.7rem", border: "1px solid var(--border)", borderRadius: "8px" }}
          />
          <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", fontSize: "0.9rem" }}>
            {t("dateFrom")}
            <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", fontSize: "0.9rem" }}>
            {t("dateTo")}
            <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          </label>
        </div>
      </div>

      {selected && (
        <div className="card">
          <h3>{t("details")}</h3>
          <p>{t("action")}: {selected.action}</p>
          <p>{t("actor")}: {selected.actor_type} — {selected.actor_id ?? "—"}</p>
          <pre
            style={{
              background: "var(--ground)",
              padding: "0.75rem",
              borderRadius: "var(--radius)",
              overflowX: "auto",
              fontSize: "0.85rem",
            }}
          >
            {JSON.stringify({ before: selected.before, after: selected.after }, null, 2)}
          </pre>
          <button className="secondary" onClick={() => setSelected(null)}>
            {t("close")}
          </button>
        </div>
      )}

      <DataTable<AuditLogEntry>
        endpoint="/platform/audit-log/"
        api={platformApi}
        hasActiveToggle={false}
        renderExtraActions={(row) => (
          <button className="secondary" onClick={() => setSelected(row)}>
            {t("details")}
          </button>
        )}
        extraParams={{
          actor_type: actorType,
          action,
          tenant_id: tenantId,
          date_from: dateFrom,
          date_to: dateTo,
        }}
        columns={[
          {
            key: "created_at",
            label: t("createdAt"),
            sortable: true,
            render: (row) => new Date(row.created_at).toLocaleString(),
          },
          { key: "actor_type", label: t("actorType") },
          { key: "action", label: t("action") },
          { key: "target_type", label: t("details") },
          { key: "tenant_id", label: t("tenants"), render: (row) => row.tenant_id ?? "—" },
        ]}
      />
    </div>
  );
}
