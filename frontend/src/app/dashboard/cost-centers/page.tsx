"use client";

import { useEffect, useState } from "react";
import { api, fieldErrors, generalError } from "@/lib/api";
import { CostCenterTree } from "@/components/CostCenterTree";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { WarningsBanner } from "@/components/WarningsBanner";
import { useLocale } from "@/lib/i18n";
import type { CostCenter, CostCenterTreeNode, CostCenterType, Paginated } from "@/lib/types";

const TYPES: CostCenterType[] = ["department", "vehicle", "warehouse", "employee", "project", "general"];

export default function CostCentersPage() {
  const { t } = useLocale();
  const [tree, setTree] = useState<CostCenterTreeNode[]>([]);
  const [flat, setFlat] = useState<CostCenter[]>([]);
  const [editing, setEditing] = useState<CostCenter | null>(null);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [centerType, setCenterType] = useState<CostCenterType>("general");
  const [parent, setParent] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});
  const [refreshToken, setRefreshToken] = useState(0);

  const loadTreeAndParents = async () => {
    const [treeData, flatData] = await Promise.all([
      api.get<CostCenterTreeNode[]>("/cost-centers/tree/"),
      api.get<Paginated<CostCenter>>("/cost-centers/"),
    ]);
    setTree(treeData);
    setFlat(flatData.results);
  };

  useEffect(() => {
    loadTreeAndParents();
  }, [refreshToken]);

  const startEdit = (center: CostCenter) => {
    setEditing(center);
    setCode(center.code);
    setName(center.name);
    setCenterType(center.center_type);
    setParent(center.parent || "");
  };

  const cancelEdit = () => {
    setEditing(null);
    setCode("");
    setName("");
    setCenterType("general");
    setParent("");
    setError(null);
    setFieldErr({});
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setFieldErr({});
    const payload = { code, name, center_type: centerType, parent: parent || null };
    try {
      if (editing) {
        await api.patch(`/cost-centers/${editing.id}/`, payload);
      } else {
        await api.post("/cost-centers/", payload);
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
      <h1>{t("costCenters")}</h1>

      <div className="card">
        <CostCenterTree roots={tree} />
      </div>

      <div className="card">
        <form onSubmit={onSubmit} style={{ display: "flex", gap: "0.75rem", alignItems: "end", flexWrap: "wrap" }}>
          <FormField name="code" required error={fieldErr.code}>
            <input value={code} onChange={(e) => setCode(e.target.value)} required />
          </FormField>
          <FormField name="name" required error={fieldErr.name}>
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </FormField>
          <FormField name="center_type" label={t("type")} error={fieldErr.center_type}>
            <select value={centerType} onChange={(e) => setCenterType(e.target.value as CostCenterType)}>
              {TYPES.map((type) => (
                <option key={type} value={type}>
                  {t(type)}
                </option>
              ))}
            </select>
          </FormField>
          <FormField name="parent" error={fieldErr.parent}>
            <select value={parent} onChange={(e) => setParent(e.target.value)}>
              <option value="">{t("none")}</option>
              {flat
                .filter((center) => center.id !== editing?.id)
                .map((center) => (
                  <option key={center.id} value={center.id}>
                    {center.code} — {center.name}
                  </option>
                ))}
            </select>
          </FormField>
          <WarningsBanner warnings={error ? [error] : []} variant="error" />
          <button className="primary" type="submit">
            {editing ? t("saveChanges") : t("add")}
          </button>
          {editing && (
            <button type="button" className="secondary" onClick={cancelEdit}>
              {t("cancel")}
            </button>
          )}
        </form>
      </div>

      <DataTable<CostCenter>
        endpoint="/cost-centers/"
        refreshToken={refreshToken}
        onEdit={startEdit}
        columns={[
          { key: "code", label: t("code"), sortable: true },
          { key: "name", label: t("name"), sortable: true },
          { key: "center_type", label: t("type"), render: (row) => t(row.center_type) },
        ]}
      />
    </div>
  );
}
