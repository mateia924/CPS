"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, fieldErrors, generalError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { Money } from "@/components/Money";
import { StatusBadge } from "@/components/StatusBadge";
import { WarningsBanner } from "@/components/WarningsBanner";
import { formatDate } from "@/lib/date";
import type { ItemCategory, LegalEntity, Paginated, StockDocument, Warehouse } from "@/lib/types";

/** Sprint 7.5 (D16): «جرد المخزون» — open a count session on one
 * warehouse (optionally narrowed to a category / search for a partial
 * count), then the list of sessions. The lines are filled server-side
 * from the balances; counting happens on the session's own screen. */
export default function StockCountsPage() {
  const { t } = useLocale();
  const { hasPermission, me } = useAuth();
  const router = useRouter();
  const canCreate = hasPermission("inventory.manage");

  const [entities, setEntities] = useState<LegalEntity[]>([]);
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [categories, setCategories] = useState<ItemCategory[]>([]);
  const [legalEntityId, setLegalEntityId] = useState("");
  const [warehouseId, setWarehouseId] = useState("");
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [categoryId, setCategoryId] = useState("");
  const [search, setSearch] = useState("");
  const [notes, setNotes] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    (async () => {
      const [entityData, warehouseData, categoryData] = await Promise.all([
        api.get<Paginated<LegalEntity>>("/legal-entities/"),
        api.get<Paginated<Warehouse>>("/warehouses/"),
        api.get<Paginated<ItemCategory>>("/inventory/item-categories/"),
      ]);
      const usable = entityData.results.filter((e) => e.entity_type !== "holding");
      setEntities(usable);
      setWarehouses(warehouseData.results.filter((w) => w.is_active));
      setCategories(categoryData.results);
      if (usable.length === 1) setLegalEntityId((prev) => prev || usable[0].id);
      else if (me?.default_legal_entity_id) setLegalEntityId((prev) => prev || me.default_legal_entity_id!);
    })();
  }, [me?.default_legal_entity_id]);

  const entityWarehouses = warehouses.filter((w) => w.legal_entity === legalEntityId);

  const open = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setFieldErr({});
    setSaving(true);
    try {
      const doc = await api.post<StockDocument>("/stock-documents/", {
        kind: "count", legal_entity: legalEntityId, warehouse: warehouseId, date,
        category: categoryId || null, search, notes,
      });
      router.push(`/dashboard/inventory/stock/${doc.id}`);
    } catch (err) {
      const body = (err as { body?: unknown }).body;
      setFieldErr(fieldErrors(body));
      setError(generalError(body, t("couldNotSave"), (err as { status?: number }).status));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <h1>{t("stockCounts")}</h1>
      <WarningsBanner warnings={error ? [error] : []} variant="error" />

      {canCreate && (
        <div className="card">
          <h3>{t("newStockCount")}</h3>
          <p style={{ color: "var(--muted)" }}>{t("stockCountOpenHint")}</p>
          <form onSubmit={open} style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end" }}>
            <FormField name="legal_entity" label={t("legalEntity")} required error={fieldErr.legal_entity}>
              <select value={legalEntityId} onChange={(e) => { setLegalEntityId(e.target.value); setWarehouseId(""); }}>
                <option value="">—</option>
                {entities.map((entity) => (
                  <option key={entity.id} value={entity.id}>{entity.code} — {entity.name}</option>
                ))}
              </select>
            </FormField>
            <FormField name="warehouse" label={t("warehouse")} required error={fieldErr.warehouse}>
              <select value={warehouseId} onChange={(e) => setWarehouseId(e.target.value)}>
                <option value="">—</option>
                {entityWarehouses.map((w) => (
                  <option key={w.id} value={w.id}>{w.code} — {w.name}</option>
                ))}
              </select>
            </FormField>
            <FormField name="date" label={t("stockCountDate")} required error={fieldErr.date}>
              <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            </FormField>
            <FormField name="category" label={t("stockCountCategory")} error={fieldErr.category}>
              <select value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
                <option value="">{t("stockCountAllCategories")}</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>{c.code} — {c.name}</option>
                ))}
              </select>
            </FormField>
            <FormField name="search" label={t("stockCountSearch")} error={fieldErr.search}>
              <input value={search} onChange={(e) => setSearch(e.target.value)} />
            </FormField>
            <FormField name="notes" label={t("notes")}>
              <input value={notes} onChange={(e) => setNotes(e.target.value)} />
            </FormField>
            <button className="primary" type="submit" disabled={saving || !warehouseId}>{t("newStockCount")}</button>
          </form>
        </div>
      )}

      <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
        <FormField name="status_filter" label={t("status")}>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("stockAllStatuses")}</option>
            {["draft", "pending_approval", "approved", "posted", "reversed"].map((s) => (
              <option key={s} value={s}>{t(s)}</option>
            ))}
          </select>
        </FormField>
      </div>

      <DataTable<StockDocument>
        endpoint="/stock-documents/"
        extraParams={{ kind: "count", status }}
        hasActiveToggle={false}
        columns={[
          { key: "number", label: t("number"), render: (row) => row.number || `(${t("draft")})` },
          { key: "date", label: t("stockCountDate"), render: (row) => formatDate(row.date, "form") },
          { key: "warehouse_name", label: t("warehouse") },
          {
            key: "count_scope", label: t("stockCountScope"),
            render: (row) => row.count_scope || t("stockCountWholeWarehouse"),
          },
          {
            key: "total_value", label: t("stockVarianceValue"),
            render: (row: StockDocument) => (
              <span title={row.total_is_estimate ? t("stockEstimate") : undefined}>
                <Money amount={row.total_value} />{row.total_is_estimate ? " *" : ""}
              </span>
            ),
          },
          { key: "status", label: t("status"), render: (row) => <StatusBadge status={row.status} /> },
        ]}
        renderExtraActions={(doc) => (
          <Link href={`/dashboard/inventory/stock/${doc.id}`} className="secondary">{t("details")}</Link>
        )}
      />
    </div>
  );
}
