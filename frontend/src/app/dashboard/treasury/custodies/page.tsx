"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { AttachmentPanel } from "@/components/AttachmentPanel";
import type { Custody, LegalEntity, Paginated, Party } from "@/lib/types";

export default function CustodiesPage() {
  const { t } = useLocale();
  const { me } = useAuth();
  const [entities, setEntities] = useState<LegalEntity[]>([]);
  const [employees, setEmployees] = useState<Party[]>([]);
  const [editing, setEditing] = useState<Custody | null>(null);
  const [legalEntityId, setLegalEntityId] = useState("");
  const [employeeId, setEmployeeId] = useState("");
  const [name, setName] = useState("");
  const [currency, setCurrency] = useState("SAR");
  const [limitAmount, setLimitAmount] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);

  useEffect(() => {
    Promise.all([
      api.get<Paginated<LegalEntity>>("/legal-entities/"),
      api.get<Paginated<Party>>("/parties/?role=employee"),
    ]).then(([entityData, employeeData]) => {
      setEntities(entityData.results);
      setEmployees(employeeData.results);
      // Sprint 6.0.1-B item 6: default to the user's own primary branch.
      if (me?.legal_entity_ids[0]) setLegalEntityId((prev) => prev || me.legal_entity_ids[0]);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const startEdit = (custody: Custody) => {
    setEditing(custody);
    setLegalEntityId(custody.legal_entity);
    setEmployeeId(custody.employee);
    setName(custody.name);
    setCurrency(custody.currency);
    setLimitAmount(custody.limit_amount ?? "");
    setError(null);
  };

  const cancelEdit = () => {
    setEditing(null);
    setLegalEntityId("");
    setEmployeeId("");
    setName("");
    setCurrency("SAR");
    setLimitAmount("");
    setError(null);
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const payload = {
      legal_entity: legalEntityId, employee: employeeId, name, currency,
      limit_amount: limitAmount || null,
    };
    try {
      if (editing) {
        await api.patch(`/custodies/${editing.id}/`, payload);
      } else {
        await api.post("/custodies/", payload);
      }
      cancelEdit();
      setRefreshToken((n) => n + 1);
    } catch {
      setError("Could not save this custody — the employee must hold the Employee role.");
    }
  };

  return (
    <div>
      <h1>{t("custodies")}</h1>

      <div className="card">
        <h3>{editing ? t("edit") : t("add")}</h3>
        <form onSubmit={onSubmit}>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <div className="form-field">
              <label>{t("name")}</label>
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </div>
            <div className="form-field">
              <label>{t("custodyEmployee")}</label>
              <select value={employeeId} onChange={(e) => setEmployeeId(e.target.value)} required>
                <option value="" disabled>
                  —
                </option>
                {employees.map((employee) => (
                  <option key={employee.id} value={employee.id}>
                    {employee.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <details style={{ marginTop: "0.75rem" }}>
            <summary style={{ cursor: "pointer" }}>{t("advanced")}</summary>
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
              <div className="form-field">
                <label>{t("legalEntity")}</label>
                <select value={legalEntityId} onChange={(e) => setLegalEntityId(e.target.value)} required>
                  <option value="" disabled>
                    —
                  </option>
                  {entities.map((entity) => (
                    <option key={entity.id} value={entity.id}>
                      {entity.code} — {entity.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-field">
                <label>{t("currency")}</label>
                <input value={currency} onChange={(e) => setCurrency(e.target.value)} maxLength={3} />
              </div>
              <div className="form-field">
                <label>{t("custodyLimit")}</label>
                <input type="number" step="0.01" value={limitAmount} onChange={(e) => setLimitAmount(e.target.value)} />
              </div>
            </div>
          </details>

          {error && <p className="error-text">{error}</p>}
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

      {editing && <AttachmentPanel targetType="custody" targetId={editing.id} />}

      <DataTable<Custody>
        endpoint="/custodies/"
        refreshToken={refreshToken}
        onEdit={startEdit}
        columns={[
          { key: "name", label: t("name"), sortable: true },
          { key: "currency", label: t("currency") },
          { key: "limit_amount", label: t("custodyLimit"), render: (row) => row.limit_amount ?? "—" },
        ]}
        renderExtraActions={(custody) => (
          <Link href={`/dashboard/treasury/custodies/${custody.id}`} className="secondary">
            {t("details")}
          </Link>
        )}
      />
    </div>
  );
}
