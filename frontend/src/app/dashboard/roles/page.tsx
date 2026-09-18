"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import type { LegalEntity, Paginated, Role, TenantUser } from "@/lib/types";

export default function RolesPage() {
  const { t } = useLocale();
  const [roles, setRoles] = useState<Role[]>([]);
  const [entities, setEntities] = useState<LegalEntity[]>([]);
  const [editing, setEditing] = useState<TenantUser | null>(null);
  const [roleIds, setRoleIds] = useState<string[]>([]);
  const [entityIds, setEntityIds] = useState<string[]>([]);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);

  const loadFormData = async () => {
    const [rolesData, entitiesData] = await Promise.all([
      api.get<Paginated<Role>>("/roles/"),
      api.get<Paginated<LegalEntity>>("/legal-entities/"),
    ]);
    setRoles(rolesData.results);
    setEntities(entitiesData.results);
  };

  useEffect(() => {
    loadFormData();
  }, []);

  const toggle = (list: string[], setList: (v: string[]) => void, id: string) => {
    setList(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
  };

  const startEdit = (user: TenantUser) => {
    setEditing(user);
    setRoleIds(user.role_ids);
    setEntityIds(user.legal_entity_ids);
    setSaveError(null);
  };

  const cancelEdit = () => {
    setEditing(null);
    setRoleIds([]);
    setEntityIds([]);
    setSaveError(null);
  };

  const onSave = async () => {
    if (!editing) return;
    setSaveError(null);
    try {
      await api.post(`/users/${editing.id}/assign/`, { role_ids: roleIds, legal_entity_ids: entityIds });
      cancelEdit();
      setRefreshToken((n) => n + 1);
    } catch {
      setSaveError("Could not save — this may be the tenant's last active Owner.");
    }
  };

  return (
    <div>
      <h1>{t("rolesAndUsers")}</h1>

      {editing && (
        <div className="card">
          <h3>
            {editing.first_name} {editing.last_name} — {editing.email}
          </h3>
          <div style={{ display: "flex", gap: "2rem", flexWrap: "wrap" }}>
            <div>
              <strong>{t("roles")}</strong>
              {roles.map((role) => (
                <label key={role.id} style={{ display: "block", fontSize: "0.9rem" }}>
                  <input
                    type="checkbox"
                    checked={roleIds.includes(role.id)}
                    onChange={() => toggle(roleIds, setRoleIds, role.id)}
                  />{" "}
                  {role.name}
                </label>
              ))}
            </div>
            <div>
              <strong>{t("entities")}</strong>
              {entities.map((entity) => (
                <label key={entity.id} style={{ display: "block", fontSize: "0.9rem" }}>
                  <input
                    type="checkbox"
                    checked={entityIds.includes(entity.id)}
                    onChange={() => toggle(entityIds, setEntityIds, entity.id)}
                  />{" "}
                  {entity.code} — {entity.name}
                </label>
              ))}
            </div>
          </div>
          {saveError && <p className="error-text">{saveError}</p>}
          <div style={{ marginTop: "1rem" }}>
            <button className="primary" onClick={onSave}>
              {t("saveChanges")}
            </button>
            <button className="secondary" onClick={cancelEdit} style={{ marginInlineStart: "0.5rem" }}>
              {t("cancel")}
            </button>
          </div>
        </div>
      )}

      <DataTable<TenantUser>
        endpoint="/users/"
        refreshToken={refreshToken}
        onEdit={startEdit}
        columns={[
          {
            key: "name",
            label: t("name"),
            render: (row) => (
              <>
                {row.first_name} {row.last_name}
                <br />
                <span style={{ color: "var(--muted)", fontSize: "0.85rem" }}>{row.email}</span>
              </>
            ),
          },
          { key: "role_names", label: t("roles"), render: (row) => row.role_names.join(", ") },
        ]}
      />
    </div>
  );
}
