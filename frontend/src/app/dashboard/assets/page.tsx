"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import Link from "next/link";
import { DataTable } from "@/components/DataTable";
import { AttachmentPanel } from "@/components/AttachmentPanel";
import type { Asset, AssetCategory, CostCenter, LegalEntity, Paginated, Party } from "@/lib/types";

const CATEGORIES: AssetCategory[] = ["vehicle", "equipment", "building", "furniture", "it", "other"];
const CATEGORY_LABEL_KEY: Record<AssetCategory, string> = {
  vehicle: "vehicle",
  equipment: "equipment",
  building: "building",
  furniture: "furniture",
  it: "it",
  other: "other",
};

export default function AssetsPage() {
  const { t } = useLocale();
  const { me } = useAuth();
  const [entities, setEntities] = useState<LegalEntity[]>([]);
  const [employees, setEmployees] = useState<Party[]>([]);
  const [costCenters, setCostCenters] = useState<CostCenter[]>([]);
  const [editing, setEditing] = useState<Asset | null>(null);

  const [legalEntityId, setLegalEntityId] = useState("");
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [category, setCategory] = useState<AssetCategory>("equipment");
  const [purchaseDate, setPurchaseDate] = useState("");
  const [purchaseCost, setPurchaseCost] = useState("");
  const [currency, setCurrency] = useState("SAR");
  const [usefulLifeMonths, setUsefulLifeMonths] = useState("");
  const [salvageValue, setSalvageValue] = useState("0");
  const [custodianId, setCustodianId] = useState("");
  const [costCenterId, setCostCenterId] = useState("");
  const [createLinkedCostCenter, setCreateLinkedCostCenter] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);

  useEffect(() => {
    Promise.all([
      api.get<Paginated<LegalEntity>>("/legal-entities/"),
      api.get<Paginated<Party>>("/parties/?role=employee"),
      api.get<Paginated<CostCenter>>("/cost-centers/"),
    ]).then(([entityData, employeeData, ccData]) => {
      setEntities(entityData.results);
      setEmployees(employeeData.results);
      setCostCenters(ccData.results);
      // Sprint 6.0.1-B item 6: default to the user's own primary branch.
      if (me?.legal_entity_ids[0]) setLegalEntityId((prev) => prev || me.legal_entity_ids[0]);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const startEdit = (asset: Asset) => {
    setEditing(asset);
    setLegalEntityId(asset.legal_entity);
    setCode(asset.code);
    setName(asset.name);
    setCategory(asset.category);
    setPurchaseDate(asset.purchase_date);
    setPurchaseCost(asset.purchase_cost);
    setCurrency(asset.currency);
    setUsefulLifeMonths(asset.useful_life_months?.toString() || "");
    setSalvageValue(asset.salvage_value);
    setCustodianId(asset.custodian || "");
    setCostCenterId(asset.cost_center || "");
    setError(null);
  };

  const cancelEdit = () => {
    setEditing(null);
    setLegalEntityId("");
    setCode("");
    setName("");
    setCategory("equipment");
    setPurchaseDate("");
    setPurchaseCost("");
    setCurrency("SAR");
    setUsefulLifeMonths("");
    setSalvageValue("0");
    setCustodianId("");
    setCostCenterId("");
    setCreateLinkedCostCenter(true);
    setError(null);
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const payload = {
      legal_entity: legalEntityId,
      code,
      name,
      category,
      purchase_date: purchaseDate,
      purchase_cost: purchaseCost,
      currency,
      useful_life_months: usefulLifeMonths || null,
      salvage_value: salvageValue,
      custodian: custodianId || null,
      cost_center: costCenterId || null,
      ...(editing ? {} : { create_linked_cost_center: category === "vehicle" ? createLinkedCostCenter : false }),
    };
    try {
      if (editing) {
        await api.patch(`/assets/${editing.id}/`, payload);
      } else {
        await api.post("/assets/", payload);
      }
      cancelEdit();
      setRefreshToken((n) => n + 1);
    } catch {
      setError("Could not save this asset.");
    }
  };

  return (
    <div>
      <h1>{t("assets")}</h1>

      <div className="card">
        <h3>{editing ? t("edit") : t("add")}</h3>
        <form onSubmit={onSubmit}>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <div className="form-field">
              <label>{t("code")}</label>
              <input value={code} onChange={(e) => setCode(e.target.value)} required />
            </div>
            <div className="form-field">
              <label>{t("name")}</label>
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </div>
            <div className="form-field">
              <label>{t("category")}</label>
              <select value={category} onChange={(e) => setCategory(e.target.value as AssetCategory)}>
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {t(CATEGORY_LABEL_KEY[c])}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-field">
              <label>{t("purchaseDate")}</label>
              <input type="date" value={purchaseDate} onChange={(e) => setPurchaseDate(e.target.value)} required />
            </div>
            <div className="form-field">
              <label>{t("purchaseCost")}</label>
              <input
                type="number"
                step="0.01"
                value={purchaseCost}
                onChange={(e) => setPurchaseCost(e.target.value)}
                required
              />
            </div>
          </div>

          {!editing && category === "vehicle" && (
            <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", marginTop: "0.5rem" }}>
              <input
                type="checkbox"
                checked={createLinkedCostCenter}
                onChange={(e) => setCreateLinkedCostCenter(e.target.checked)}
              />
              {t("createLinkedCostCenter")}
            </label>
          )}

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
                <label>{t("usefulLifeMonths")}</label>
                <input
                  type="number"
                  value={usefulLifeMonths}
                  onChange={(e) => setUsefulLifeMonths(e.target.value)}
                />
              </div>
              <div className="form-field">
                <label>{t("salvageValue")}</label>
                <input
                  type="number"
                  step="0.01"
                  value={salvageValue}
                  onChange={(e) => setSalvageValue(e.target.value)}
                />
              </div>
              <div className="form-field">
                <label>{t("custodian")}</label>
                <select value={custodianId} onChange={(e) => setCustodianId(e.target.value)}>
                  <option value="">{t("none")}</option>
                  {employees.map((employee) => (
                    <option key={employee.id} value={employee.id}>
                      {employee.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-field">
                <label>{t("costCenter")}</label>
                <select value={costCenterId} onChange={(e) => setCostCenterId(e.target.value)}>
                  <option value="">{t("none")}</option>
                  {costCenters.map((cc) => (
                    <option key={cc.id} value={cc.id}>
                      {cc.code} — {cc.name}
                    </option>
                  ))}
                </select>
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

      {editing && <AttachmentPanel targetType="asset" targetId={editing.id} />}

      <DataTable<Asset>
        endpoint="/assets/"
        refreshToken={refreshToken}
        onEdit={startEdit}
        columns={[
          { key: "code", label: t("code"), sortable: true },
          { key: "name", label: t("name"), sortable: true },
          { key: "category", label: t("category"), render: (row) => t(CATEGORY_LABEL_KEY[row.category]) },
          { key: "status", label: t("assetStatus"), render: (row) => t(row.status === "under_maintenance" ? "underMaintenance" : row.status === "disposed" ? "disposed" : "active") },
          {
            key: "disposed_fraction",
            label: "",
            render: (row) => {
              const fraction = Number(row.disposed_fraction);
              if (row.status === "disposed" || fraction >= 1) return t("fullyDisposedBadge");
              if (fraction > 0) return t("partiallyDisposedBadge");
              return "";
            },
          },
          {
            key: "id",
            label: "",
            render: (row) => <Link href={`/dashboard/assets/${row.id}`}>{t("viewDetails")}</Link>,
          },
        ]}
      />
    </div>
  );
}
