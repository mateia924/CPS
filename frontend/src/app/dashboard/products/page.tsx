"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, fieldErrors, generalError } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { Money } from "@/components/Money";
import { WarningsBanner } from "@/components/WarningsBanner";
import { ImportItemsCsvCard } from "@/components/ImportItemsCsvCard";
import type { ItemCategory, ItemTracking, ItemType, Paginated, Product, UnitOfMeasure } from "@/lib/types";

export default function ProductsPage() {
  const { t } = useLocale();
  const [categories, setCategories] = useState<ItemCategory[]>([]);
  const [units, setUnits] = useState<UnitOfMeasure[]>([]);

  const [editing, setEditing] = useState<Product | null>(null);
  const [sku, setSku] = useState("");
  const [name, setName] = useState("");
  const [unitPrice, setUnitPrice] = useState("");
  const [taxRate, setTaxRate] = useState("0");
  const [itemType, setItemType] = useState<ItemType>("service");
  const [category, setCategory] = useState("");
  const [baseUom, setBaseUom] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});
  const [refreshToken, setRefreshToken] = useState(0);

  // D7/sprint-7.md: list-level filters, separate from the free-text
  // search box (which already covers code/name/barcode/part number —
  // see ProductViewSet.search_fields).
  const [filterItemType, setFilterItemType] = useState("");
  const [filterCategory, setFilterCategory] = useState("");
  const [filterTracking, setFilterTracking] = useState<ItemTracking | "">("");

  useEffect(() => {
    Promise.all([
      api.get<Paginated<ItemCategory>>("/inventory/item-categories/?page_size=200"),
      api.get<Paginated<UnitOfMeasure>>("/inventory/units/?page_size=200"),
    ]).then(([catData, unitData]) => {
      setCategories(catData.results);
      setUnits(unitData.results);
    });
  }, []);

  const startEdit = (product: Product) => {
    setEditing(product);
    setSku(product.sku);
    setName(product.name);
    setUnitPrice(product.unit_price);
    setTaxRate(product.tax_rate);
    setItemType(product.item_type);
    setCategory(product.category || "");
    setBaseUom(product.base_uom || "");
    setError(null);
    setFieldErr({});
  };

  const cancelEdit = () => {
    setEditing(null);
    setSku("");
    setName("");
    setUnitPrice("");
    setTaxRate("0");
    setItemType("service");
    setCategory("");
    setBaseUom("");
    setError(null);
    setFieldErr({});
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setFieldErr({});
    const payload = {
      sku, name, unit_price: unitPrice, tax_rate: taxRate,
      item_type: itemType, category: category || null, base_uom: baseUom || null,
    };
    try {
      if (editing) {
        await api.patch(`/products/${editing.id}/`, payload);
      } else {
        await api.post("/products/", payload);
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
      <h1>{t("items")}</h1>
      <div className="card">
        <h3>{editing ? t("edit") : t("add")}</h3>
        <form onSubmit={onSubmit} style={{ display: "flex", gap: "0.75rem", alignItems: "end", flexWrap: "wrap" }}>
          <FormField name="sku" label={t("sku")} required error={fieldErr.sku}>
            <input value={sku} onChange={(e) => setSku(e.target.value)} required />
          </FormField>
          <FormField name="name" label={t("name")} required error={fieldErr.name}>
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </FormField>
          <FormField name="item_type" label={t("itemType")} error={fieldErr.item_type}>
            <select value={itemType} onChange={(e) => setItemType(e.target.value as ItemType)}>
              <option value="service">{t("itemTypeService")}</option>
              <option value="stock">{t("itemTypeStock")}</option>
            </select>
          </FormField>
          <FormField name="category" label={t("category")} error={fieldErr.category}>
            <select value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">{t("noCategory")}</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.code} {c.name}
                </option>
              ))}
            </select>
          </FormField>
          {itemType === "stock" && (
            <FormField name="base_uom" label={t("baseUom")} error={fieldErr.base_uom}>
              <select value={baseUom} onChange={(e) => setBaseUom(e.target.value)}>
                <option value="">—</option>
                {units.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.code} {u.name_ar}
                  </option>
                ))}
              </select>
            </FormField>
          )}
          <FormField name="unit_price" label={t("unitPrice")} required error={fieldErr.unit_price}>
            <input type="number" step="0.01" value={unitPrice} onChange={(e) => setUnitPrice(e.target.value)} required />
          </FormField>
          <FormField name="tax_rate" label={t("taxRate")} error={fieldErr.tax_rate}>
            <input type="number" step="0.01" value={taxRate} onChange={(e) => setTaxRate(e.target.value)} />
          </FormField>
          <button className="primary" type="submit">
            {editing ? t("saveChanges") : t("add")}
          </button>
          {editing && (
            <button type="button" className="secondary" onClick={cancelEdit}>
              {t("cancel")}
            </button>
          )}
        </form>
        <WarningsBanner warnings={error ? [error] : []} variant="error" />
      </div>

      <ImportItemsCsvCard onImported={() => setRefreshToken((n) => n + 1)} />

      <div className="card">
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
          <FormField name="filter_item_type" label={t("itemType")}>
            <select value={filterItemType} onChange={(e) => setFilterItemType(e.target.value)}>
              <option value="">{t("all")}</option>
              <option value="service">{t("itemTypeService")}</option>
              <option value="stock">{t("itemTypeStock")}</option>
            </select>
          </FormField>
          <FormField name="filter_category" label={t("category")}>
            <select value={filterCategory} onChange={(e) => setFilterCategory(e.target.value)}>
              <option value="">{t("all")}</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.code} {c.name}
                </option>
              ))}
            </select>
          </FormField>
          <FormField name="filter_tracking" label={t("tracking")}>
            <select value={filterTracking} onChange={(e) => setFilterTracking(e.target.value as ItemTracking)}>
              <option value="">{t("all")}</option>
              <option value="none">{t("trackingNone")}</option>
              <option value="serial">{t("trackingSerial")}</option>
              <option value="batch">{t("trackingBatch")}</option>
            </select>
          </FormField>
        </div>
      </div>

      <DataTable<Product>
        endpoint="/products/"
        refreshToken={refreshToken}
        onEdit={startEdit}
        hasActiveToggle
        extraParams={{ item_type: filterItemType, category: filterCategory, tracking: filterTracking }}
        renderExtraActions={(product) => (
          <Link href={`/dashboard/products/${product.id}`} className="secondary">
            {t("viewDetails")}
          </Link>
        )}
        columns={[
          { key: "sku", label: t("sku"), sortable: true },
          { key: "name", label: t("name"), sortable: true },
          { key: "item_type", label: t("itemType"), render: (row) => (row.item_type === "stock" ? t("itemTypeStock") : t("itemTypeService")) },
          { key: "unit_price", label: t("unitPrice"), sortable: true, render: (row) => <Money amount={row.unit_price} /> },
          { key: "tax_rate", label: t("taxRate") },
        ]}
      />
    </div>
  );
}
