"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import type { LegalEntity, Paginated, Role, TenantUser } from "@/lib/types";

function UserRow({
  user,
  roles,
  entities,
  onSaved,
}: {
  user: TenantUser;
  roles: Role[];
  entities: LegalEntity[];
  onSaved: () => void;
}) {
  const { t } = useLocale();
  const [roleIds, setRoleIds] = useState<string[]>(user.role_ids);
  const [entityIds, setEntityIds] = useState<string[]>(user.legal_entity_ids);
  const [saving, setSaving] = useState(false);

  const toggle = (list: string[], setList: (v: string[]) => void, id: string) => {
    setList(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
  };

  const save = async () => {
    setSaving(true);
    try {
      await api.post(`/users/${user.id}/assign/`, {
        role_ids: roleIds,
        legal_entity_ids: entityIds,
      });
      onSaved();
    } finally {
      setSaving(false);
    }
  };

  return (
    <tr>
      <td>
        {user.first_name} {user.last_name}
        <br />
        <span style={{ color: "var(--muted)", fontSize: "0.85rem" }}>{user.email}</span>
      </td>
      <td>
        {roles.map((role) => (
          <label key={role.id} style={{ display: "block", fontSize: "0.85rem" }}>
            <input
              type="checkbox"
              checked={roleIds.includes(role.id)}
              onChange={() => toggle(roleIds, setRoleIds, role.id)}
            />{" "}
            {role.name}
          </label>
        ))}
      </td>
      <td>
        {entities.map((entity) => (
          <label key={entity.id} style={{ display: "block", fontSize: "0.85rem" }}>
            <input
              type="checkbox"
              checked={entityIds.includes(entity.id)}
              onChange={() => toggle(entityIds, setEntityIds, entity.id)}
            />{" "}
            {entity.code}
          </label>
        ))}
      </td>
      <td>
        <button className="secondary" onClick={save} disabled={saving}>
          {t("save")}
        </button>
      </td>
    </tr>
  );
}

export default function RolesPage() {
  const { t } = useLocale();
  const [users, setUsers] = useState<TenantUser[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [entities, setEntities] = useState<LegalEntity[]>([]);

  const load = async () => {
    const [usersData, rolesData, entitiesData] = await Promise.all([
      api.get<Paginated<TenantUser>>("/users/"),
      api.get<Paginated<Role>>("/roles/"),
      api.get<Paginated<LegalEntity>>("/legal-entities/"),
    ]);
    setUsers(usersData.results);
    setRoles(rolesData.results);
    setEntities(entitiesData.results);
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <div>
      <h1>{t("rolesAndUsers")}</h1>
      <table>
        <thead>
          <tr>
            <th>{t("name")}</th>
            <th>{t("roles")}</th>
            <th>{t("entities")}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {users.map((user) => (
            <UserRow key={user.id} user={user} roles={roles} entities={entities} onSaved={load} />
          ))}
        </tbody>
      </table>
    </div>
  );
}
