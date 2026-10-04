"use client";

import { useEffect, useState } from "react";
import { api, fieldErrors, generalError } from "@/lib/api";
import { flattenLeafAccounts, type FlatAccountOption } from "@/lib/accounts";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { WarningsBanner } from "@/components/WarningsBanner";
import type { AccountTreeNode, ItemCategory, ItemTracking, Paginated, UnitOfMeasure } from "@/lib/types";

export default function ItemCategoriesPage() {
  const { t } = useLocale();
  const [categories, setCategories] = useState<ItemCategory[]>([]);
  const [units, setUnits] = useState<UnitOfMeasure[]>([]);
  const [accounts, setAccounts] = useState<FlatAccountOption[]>([]);

  const [editing, setEditing] = useState<ItemCategory | null>(null);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [parent, setParent] = useState("");
  const [defaultTracking, setDefaultTracking] = useState<ItemTracking>("");
  const [defaultUom, setDefaultUom] = useState("");
  const [defaultInventoryAccount, setDefaultInventoryAccount] = useState("");
  const [defaultCogsAccount, setDefaultCogsAccount] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});
  const [refreshToken, setRefreshToken] = useState(0);

  useEffect(() => {
    Promise.all([
      api.get<Paginated<ItemCategory>>("/inventory/item-categories/?page_size=200"),
      api.get<Paginated<UnitOfMeasure>>("/inventory/units/?page_size=200"),
      api.get<AccountTreeNode[]>("/accounts/tree/"),
    ]).then(([catData, unitData, accountTree]) => {
      setCategories(catData.results);
      setUnits(unitData.results);
      setAccounts(flattenLeafAccounts(accountTree));
    });
  }, [refreshToken]);

  const startEdit = (cat: ItemCategory) => {
    setEditing(cat);
    setCode(cat.code);
    setName(cat.name);
    setParent(cat.parent || "");
    setDefaultTracking(cat.default_tracking);
    setDefaultUom(cat.default_uom || "");
    setDefaultInventoryAccount(cat.default_inventory_account || "");
    setDefaultCogsAccount(cat.default_cogs_account || "");
    setError(null);
    setFieldErr({});
  };

  const cancelEdit = () => {
    setEditing(null);
    setCode("");
    setName("");
    setParent("");
    setDefaultTracking("");
    setDefaultUom("");
    setDefaultInventoryAccount("");
    setDefaultCogsAccount("");
    setError(null);
    setFieldErr({});
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setFieldErr({});
    const payload = {
      code,
      name,
      parent: parent || null,
      default_tracking: defaultTracking,
      default_uom: defaultUom || null,
      default_inventory_account: defaultInventoryAccount || null,
      default_cogs_account: defaultCogsAccount || null,
    };
    try {
      if (editing) {
        await api.patch(`/inventory/item-categories/${editing.id}/`, payload);
      } else {
        await api.post("/inventory/item-categories/", payload);
      }
      cancelEdit();
      setRefreshToken((n) => n + 1);
    } catch (err) {
      setFieldErr(fieldErrors((err as { body?: unknown }).body));
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  return (
    <div>
      <h1>{t("itemCategories")}</h1>
      <div className="card">
        <h3>{editing ? t("edit") : t("add")}</h3>
        <form onSubmit={onSubmit}>
          <div style={{ display: "flex", gap: "0.75rem", alignItems: "end", flexWrap: "wrap" }}>
            <FormField name="code" label={t("code")} required error={fieldErr.code}>
              <input value={code} onChange={(e) => setCode(e.target.value)} required />
            </FormField>
            <FormField name="name" label={t("name")} required error={fieldErr.name}>
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </FormField>
            <FormField name="parent" label={t("category")} error={fieldErr.parent}>
              <select value={parent} onChange={(e) => setParent(e.target.value)}>
                <option value="">{t("noCategory")}</option>
                {categories
                  .filter((c) => !editing || c.id !== editing.id)
                  .map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.code} {c.name}
                    </option>
                  ))}
              </select>
            </FormField>
            <FormField name="default_tracking" label={t("tracking")} error={fieldErr.default_tracking}>
              <select value={defaultTracking} onChange={(e) => setDefaultTracking(e.target.value as ItemTracking)}>
                <option value="">—</option>
                <option value="none">{t("trackingNone")}</option>
                <option value="serial">{t("trackingSerial")}</option>
                <option value="batch">{t("trackingBatch")}</option>
              </select>
            </FormField>
            <FormField name="default_uom" label={t("baseUom")} error={fieldErr.default_uom}>
              <select value={defaultUom} onChange={(e) => setDefaultUom(e.target.value)}>
                <option value="">—</option>
                {units.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.code} {u.name_ar}
                  </option>
                ))}
              </select>
            </FormField>
          </div>

          <details style={{ marginTop: "0.75rem" }}>
            <summary style={{ cursor: "pointer" }}>{t("advanced")}</summary>
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
              <FormField name="default_inventory_account" label={t("inventoryAccountOverride")} error={fieldErr.default_inventory_account}>
                <select value={defaultInventoryAccount} onChange={(e) => setDefaultInventoryAccount(e.target.value)}>
                  <option value="">—</option>
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.label}
                    </option>
                  ))}
                </select>
              </FormField>
              <FormField name="default_cogs_account" label={t("cogsAccountOverride")} error={fieldErr.default_cogs_account}>
                <select value={defaultCogsAccount} onChange={(e) => setDefaultCogsAccount(e.target.value)}>
                  <option value="">—</option>
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.label}
                    </option>
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

      <DataTable<ItemCategory>
        endpoint="/inventory/item-categories/"
        refreshToken={refreshToken}
        onEdit={startEdit}
        hasActiveToggle
        columns={[
          { key: "code", label: t("code"), sortable: true },
          { key: "name", label: t("name"), sortable: true },
        ]}
      />
    </div>
  );
}
