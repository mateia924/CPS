"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { Money } from "@/components/Money";
import type { LegalEntity, Paginated, StockLevelRow, Warehouse } from "@/lib/types";

/** Sprint 7.4: «أرصدة المخزون» — quantity per item per warehouse, valued
 * at the company's moving average (server-computed, read-only). */
export default function StockBalancesPage() {
  const { t } = useLocale();
  const [entities, setEntities] = useState<LegalEntity[]>([]);
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [entityId, setEntityId] = useState("");
  const [warehouseId, setWarehouseId] = useState("");
  const [nonzero, setNonzero] = useState(true);

  useEffect(() => {
    api.get<Paginated<LegalEntity>>("/legal-entities/").then((d) =>
      setEntities(d.results.filter((e) => e.entity_type !== "holding")),
    );
    api.get<Paginated<Warehouse>>("/warehouses/").then((d) => setWarehouses(d.results));
  }, []);

  return (
    <div>
      <h1>{t("stockBalances")}</h1>
      <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end" }}>
        <FormField name="entity_filter" label={t("entityFilter")}>
          <select value={entityId} onChange={(e) => setEntityId(e.target.value)}>
            <option value="">{t("allEntities")}</option>
            {entities.map((e) => (
              <option key={e.id} value={e.id}>{e.code} — {e.name}</option>
            ))}
          </select>
        </FormField>
        <FormField name="warehouse_filter" label={t("warehouse")}>
          <select value={warehouseId} onChange={(e) => setWarehouseId(e.target.value)}>
            <option value="">{t("stockAllWarehouses")}</option>
            {warehouses.map((w) => (
              <option key={w.id} value={w.id}>{w.code} — {w.name}</option>
            ))}
          </select>
        </FormField>
        <label style={{ display: "flex", gap: "0.3rem", alignItems: "center" }}>
          <input type="checkbox" checked={nonzero} onChange={(e) => setNonzero(e.target.checked)} /> {/* form-ok: GET-only filter */}
          {t("stockOnlyNonzero")}
        </label>
      </div>
      <DataTable<StockLevelRow>
        endpoint="/stock-levels/"
        extraParams={{ legal_entity: entityId, warehouse: warehouseId, nonzero: nonzero ? "true" : "" }}
        hasActiveToggle={false}
        columns={[
          { key: "item", label: t("stockItem"), render: (r) => `${r.item_sku} — ${r.item_name}` },
          { key: "warehouse_name", label: t("warehouse") },
          { key: "legal_entity_name", label: t("legalEntity") },
          { key: "qty_on_hand", label: t("stockQtyOnHand"), render: (r) => <span className="money">{r.qty_on_hand}</span> },
          { key: "avg_cost", label: t("stockAvgCost"), render: (r) => <Money amount={r.avg_cost} /> },
          { key: "value", label: t("stockTotalValue"), render: (r) => <Money amount={r.value} /> },
        ]}
      />
    </div>
  );
}
