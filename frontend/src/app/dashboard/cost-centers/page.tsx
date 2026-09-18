"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { CostCenterTree } from "@/components/CostCenterTree";
import { useLocale } from "@/lib/i18n";
import type { CostCenter, CostCenterTreeNode, CostCenterType, Paginated } from "@/lib/types";

const TYPES: CostCenterType[] = ["department", "vehicle", "warehouse", "employee", "project", "general"];

export default function CostCentersPage() {
  const { t } = useLocale();
  const [tree, setTree] = useState<CostCenterTreeNode[]>([]);
  const [flat, setFlat] = useState<CostCenter[]>([]);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [centerType, setCenterType] = useState<CostCenterType>("general");
  const [parent, setParent] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    const [treeData, flatData] = await Promise.all([
      api.get<CostCenterTreeNode[]>("/cost-centers/tree/"),
      api.get<Paginated<CostCenter>>("/cost-centers/"),
    ]);
    setTree(treeData);
    setFlat(flatData.results);
  };

  useEffect(() => {
    load();
  }, []);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await api.post("/cost-centers/", {
        code,
        name,
        center_type: centerType,
        parent: parent || null,
      });
      setCode("");
      setName("");
      setParent("");
      await load();
    } catch {
      setError("Could not create this cost center — check code uniqueness.");
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
          <div className="form-field">
            <label>{t("code")}</label>
            <input value={code} onChange={(e) => setCode(e.target.value)} required />
          </div>
          <div className="form-field">
            <label>{t("name")}</label>
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="form-field">
            <label>{t("type")}</label>
            <select value={centerType} onChange={(e) => setCenterType(e.target.value as CostCenterType)}>
              {TYPES.map((type) => (
                <option key={type} value={type}>
                  {t(type)}
                </option>
              ))}
            </select>
          </div>
          <div className="form-field">
            <label>{t("parent")}</label>
            <select value={parent} onChange={(e) => setParent(e.target.value)}>
              <option value="">{t("none")}</option>
              {flat.map((center) => (
                <option key={center.id} value={center.id}>
                  {center.code} — {center.name}
                </option>
              ))}
            </select>
          </div>
          {error && <p className="error-text">{error}</p>}
          <button className="primary" type="submit">
            {t("add")}
          </button>
        </form>
      </div>
    </div>
  );
}
