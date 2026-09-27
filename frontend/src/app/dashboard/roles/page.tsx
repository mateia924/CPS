"use client";

import { useEffect, useState } from "react";
import { api, fieldErrors, generalError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { roleLabel, useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { WarningsBanner } from "@/components/WarningsBanner";
import type { LegalEntity, Paginated, Role, TenantUser } from "@/lib/types";

export default function RolesPage() {
  const { t } = useLocale();
  const { me } = useAuth();
  const [roles, setRoles] = useState<Role[]>([]);
  const [entities, setEntities] = useState<LegalEntity[]>([]);
  const [editing, setEditing] = useState<TenantUser | null>(null);
  const [roleIds, setRoleIds] = useState<string[]>([]);
  const [entityIds, setEntityIds] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});
  const [refreshToken, setRefreshToken] = useState(0);

  // Sprint 6.5.10 (UAT note 8): "مستخدم جديد" — POST /users/ (name,
  // email, temp password, allowed entities) then POST /users/{id}/
  // assign/ (roles) right after, so the whole thing is one form
  // submission instead of "create, then remember to also go assign
  // roles" (the exact sprint-5.0 gotcha /assign/'s own docstring
  // already warns about for entity access — same shape of mistake).
  const [showNewUser, setShowNewUser] = useState(false);
  const [newFirstName, setNewFirstName] = useState("");
  const [newLastName, setNewLastName] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRoleIds, setNewRoleIds] = useState<string[]>([]);
  const [newEntityIds, setNewEntityIds] = useState<string[]>([]);
  const [newUserError, setNewUserError] = useState<string | null>(null);
  const [newUserFieldErr, setNewUserFieldErr] = useState<Record<string, string>>({});

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
    setError(null);
  };

  const cancelEdit = () => {
    setEditing(null);
    setRoleIds([]);
    setEntityIds([]);
    setError(null);
  };

  const onSave = async () => {
    if (!editing) return;
    setError(null);
    try {
      await api.post(`/users/${editing.id}/assign/`, { role_ids: roleIds, legal_entity_ids: entityIds });
      cancelEdit();
      setRefreshToken((n) => n + 1);
    } catch (err) {
      setError(generalError((err as { body?: unknown }).body, t("couldNotSaveLastOwnerHint")));
    }
  };

  const cancelNewUser = () => {
    setShowNewUser(false);
    setNewFirstName("");
    setNewLastName("");
    setNewEmail("");
    setNewPassword("");
    setNewRoleIds([]);
    setNewEntityIds([]);
    setNewUserError(null);
    setNewUserFieldErr({});
  };

  const onCreateUser = async () => {
    setNewUserError(null);
    setNewUserFieldErr({});
    try {
      const created = await api.post<TenantUser>("/users/", {
        first_name: newFirstName,
        last_name: newLastName,
        email: newEmail,
        password: newPassword,
        legal_entity_ids: newEntityIds,
      });
      if (newRoleIds.length > 0) {
        await api.post(`/users/${created.id}/assign/`, { role_ids: newRoleIds });
      }
      cancelNewUser();
      setRefreshToken((n) => n + 1);
    } catch (err) {
      const body = (err as { body?: unknown; status?: number }).body;
      const status = (err as { status?: number }).status;
      if (status === 402) {
        setNewUserError(generalError(body, t("maxUsersReached")));
        return;
      }
      setNewUserFieldErr(fieldErrors(body));
      setNewUserError(generalError(body, t("couldNotSave")));
    }
  };

  return (
    <div>
      <h1>{t("rolesAndUsers")}</h1>

      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h3 style={{ margin: 0 }}>{t("newUser")}</h3>
          <button className="secondary" onClick={() => setShowNewUser((v) => !v)}>
            {t("newUser")}
          </button>
        </div>
        {showNewUser && (
          <div style={{ marginTop: "0.75rem" }}>
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
              <FormField name="first_name" error={newUserFieldErr.first_name}>
                <input value={newFirstName} onChange={(e) => setNewFirstName(e.target.value)} />
              </FormField>
              <FormField name="last_name" error={newUserFieldErr.last_name}>
                <input value={newLastName} onChange={(e) => setNewLastName(e.target.value)} />
              </FormField>
              <FormField name="email" required error={newUserFieldErr.email}>
                <input type="email" value={newEmail} onChange={(e) => setNewEmail(e.target.value)} required />
              </FormField>
              <FormField name="password" label={t("temporaryPassword")} required error={newUserFieldErr.password}>
                <input
                  type="text"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  required
                />
              </FormField>
            </div>
            <div style={{ display: "flex", gap: "2rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
              <div>
                <strong>{t("roles")}</strong>
                {roles.map((role) => (
                  <label key={role.id} style={{ display: "block", fontSize: "0.9rem" }}>
                    <input
                      type="checkbox"
                      checked={newRoleIds.includes(role.id)}
                      onChange={() => toggle(newRoleIds, setNewRoleIds, role.id)}
                      // form-ok: a multi-select group, not a single backend field of its own
                    />{" "}
                    {roleLabel(t, role.name)}
                  </label>
                ))}
              </div>
              {entities.length > 1 && (
                <div>
                  <strong>{t("entities")}</strong>
                  {entities.map((entity) => (
                    <label key={entity.id} style={{ display: "block", fontSize: "0.9rem" }}>
                      <input
                        type="checkbox"
                        checked={newEntityIds.includes(entity.id)}
                        onChange={() => toggle(newEntityIds, setNewEntityIds, entity.id)}
                        // form-ok: a multi-select group, not a single backend field of its own
                      />{" "}
                      {entity.code} — {entity.name}
                    </label>
                  ))}
                </div>
              )}
            </div>
            <WarningsBanner warnings={newUserError ? [newUserError] : []} variant="error" />
            <div style={{ marginTop: "0.75rem" }}>
              <button className="primary" onClick={onCreateUser}>
                {t("add")}
              </button>
              <button className="secondary" onClick={cancelNewUser} style={{ marginInlineStart: "0.5rem" }}>
                {t("cancel")}
              </button>
            </div>
          </div>
        )}
      </div>

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
                  {roleLabel(t, role.name)}
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
          <WarningsBanner warnings={error ? [error] : []} variant="error" />
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
          {
            key: "role_names",
            label: t("roles"),
            render: (row) => row.role_names.map((name) => roleLabel(t, name)).join(", "),
          },
        ]}
      />
    </div>
  );
}
