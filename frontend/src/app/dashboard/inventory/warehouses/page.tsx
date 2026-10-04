"use client";

import { useEffect, useState } from "react";
import { api, fieldErrors, generalError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { flattenLeafAccounts, type FlatAccountOption } from "@/lib/accounts";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { WarningsBanner } from "@/components/WarningsBanner";
import type { AccountTreeNode, CostCenter, LegalEntity, Paginated, Warehouse } from "@/lib/types";

export default function WarehousesPage() {
  const { t } = useLocale();
  const { me } = useAuth();
  const [entities, setEntities] = useState<LegalEntity[]>([]);
  const [costCenters, setCostCenters] = useState<CostCenter[]>([]);
  const [accounts, setAccounts] = useState<FlatAccountOption[]>([]);

  const [editing, setEditing] = useState<Warehouse | null>(null);
  const [legalEntityId, setLegalEntityId] = useState("");
  const [listEntityId, setListEntityId] = useState("");
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [costCenterId, setCostCenterId] = useState("");
  const [inventoryAccount, setInventoryAccount] = useState("");
  const [cogsAccount, setCogsAccount] = useState("");
  const [adjustmentAccount, setAdjustmentAccount] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});
  const [refreshToken, setRefreshToken] = useState(0);

  useEffect(() => {
    Promise.all([
      api.get<Paginated<LegalEntity>>("/legal-entities/"),
      api.get<Paginated<CostCenter>>("/cost-centers/?page_size=200"),
      api.get<AccountTreeNode[]>("/accounts/tree/"),
    ]).then(([entityData, costCenterData, accountTree]) => {
      setEntities(entityData.results);
      setCostCenters(costCenterData.results);
      setAccounts(flattenLeafAccounts(accountTree));
      if (me?.default_legal_entity_id) setLegalEntityId((prev) => prev || me.default_legal_entity_id!);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const startEdit = (warehouse: Warehouse) => {
    setEditing(warehouse);
    setLegalEntityId(warehouse.legal_entity);
    setCode(warehouse.code);
    setName(warehouse.name);
    setCostCenterId(warehouse.cost_center || "");
    setInventoryAccount(warehouse.inventory_account_override || "");
    setCogsAccount(warehouse.cogs_account_override || "");
    setAdjustmentAccount(warehouse.adjustment_account_override || "");
    setError(null);
    setFieldErr({});
  };

  const cancelEdit = () => {
    setEditing(null);
    setLegalEntityId("");
    setCode("");
    setName("");
    setCostCenterId("");
    setInventoryAccount("");
    setCogsAccount("");
    setAdjustmentAccount("");
    setError(null);
    setFieldErr({});
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setFieldErr({});
    const payload = {
      legal_entity: legalEntityId, code, name,
      cost_center: costCenterId || null,
      inventory_account_override: inventoryAccount || null,
      cogs_account_override: cogsAccount || null,
      adjustment_account_override: adjustmentAccount || null,
    };
    try {
      if (editing) {
        await api.patch(`/warehouses/${editing.id}/`, payload);
      } else {
        await api.post("/warehouses/", payload);
      }
      cancelEdit();
      setRefreshToken((n) => n + 1);
    } catch (err) {
      setFieldErr(fieldErrors((err as { body?: unknown }).body));
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const makeDefault = async (warehouse: Warehouse, reload: () => void) => {
    await api.post(`/warehouses/${warehouse.id}/set-default/`);
    reload();
  };

  return (
    <div>
      <h1>{t("warehouses")}</h1>

      <div className="card">
        <h3>{editing ? t("edit") : t("add")}</h3>
        <form onSubmit={onSubmit}>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <FormField name="legal_entity" label={t("legalEntity")} required error={fieldErr.legal_entity}>
              <select value={legalEntityId} onChange={(e) => setLegalEntityId(e.target.value)} required>
                <option value="" disabled>—</option>
                {entities.map((entity) => (
                  <option key={entity.id} value={entity.id}>
                    {entity.code} — {entity.name}
                  </option>
                ))}
              </select>
            </FormField>
            <FormField name="code" label={t("code")} required error={fieldErr.code}>
              <input value={code} onChange={(e) => setCode(e.target.value)} required />
            </FormField>
            <FormField name="name" label={t("name")} required error={fieldErr.name}>
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </FormField>
          </div>

          <details style={{ marginTop: "0.75rem" }}>
            <summary style={{ cursor: "pointer" }}>{t("advanced")}</summary>
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
              <FormField name="cost_center" label={t("costCenter")} error={fieldErr.cost_center}>
                <select value={costCenterId} onChange={(e) => setCostCenterId(e.target.value)}>
                  <option value="">—</option>
                  {costCenters.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.code} {c.name}
                    </option>
                  ))}
                </select>
              </FormField>
              <FormField name="inventory_account_override" label={t("inventoryAccountOverride")} error={fieldErr.inventory_account_override}>
                <select value={inventoryAccount} onChange={(e) => setInventoryAccount(e.target.value)}>
                  <option value="">—</option>
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>{a.label}</option>
                  ))}
                </select>
              </FormField>
              <FormField name="cogs_account_override" label={t("cogsAccountOverride")} error={fieldErr.cogs_account_override}>
                <select value={cogsAccount} onChange={(e) => setCogsAccount(e.target.value)}>
                  <option value="">—</option>
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>{a.label}</option>
                  ))}
                </select>
              </FormField>
              <FormField name="adjustment_account_override" label={t("adjustmentAccountOverride")} error={fieldErr.adjustment_account_override}>
                <select value={adjustmentAccount} onChange={(e) => setAdjustmentAccount(e.target.value)}>
                  <option value="">—</option>
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>{a.label}</option>
                  ))}
                </select>
              </FormField>
            </div>
          </details>

          <WarningsBanner warnings={error ? [error] : []} variant="error" />
          <button className="primary" type="submit" style={{ marginTop: "0.75rem" }}>
            {editing ? t("saveChanges") : t("add")}
          </button>
          {editing && (
            <button type="button" className="secondary" style={{ marginTop: "0.75rem", marginInlineStart: "0.5rem" }} onClick={cancelEdit}>
              {t("cancel")}
            </button>
          )}
        </form>
      </div>

      <FormField name="list_entity_filter" label={t("entityFilter")}>
        <select value={listEntityId} onChange={(e) => setListEntityId(e.target.value)}>
          <option value="">{t("allEntities")}</option>
          {entities.map((entity) => (
            <option key={entity.id} value={entity.id}>{entity.code} — {entity.name}</option>
          ))}
        </select>
      </FormField>

      <DataTable<Warehouse>
        endpoint="/warehouses/"
        extraParams={{ legal_entity: listEntityId }}
        refreshToken={refreshToken}
        onEdit={startEdit}
        hasActiveToggle
        columns={[
          { key: "code", label: t("code"), sortable: true },
          { key: "name", label: t("name"), sortable: true },
          {
            key: "legal_entity",
            label: t("legalEntity"),
            render: (row) => {
              const entity = entities.find((e) => e.id === row.legal_entity);
              return entity ? `${entity.code} — ${entity.name}` : row.legal_entity;
            },
          },
          {
            key: "is_default",
            label: t("defaultWarehouse"),
            render: (row) =>
              row.is_default ? (
                <span
                  style={{
                    display: "inline-block", padding: "0.15rem 0.6rem", borderRadius: "var(--radius-pill)",
                    fontSize: "0.8rem", fontWeight: 600,
                    color: "var(--status-posted)", background: "var(--status-posted-bg)",
                  }}
                >
                  {t("defaultWarehouse")}
                </span>
              ) : null,
          },
        ]}
        renderExtraActions={(warehouse, reload) =>
          !warehouse.is_default && (
            <button className="secondary" onClick={() => makeDefault(warehouse, reload)}>
              {t("makeDefault")}
            </button>
          )
        }
      />
    </div>
  );
}
