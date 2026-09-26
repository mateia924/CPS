"use client";

import { useState } from "react";
import { api, fieldErrors, generalError } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { Money } from "@/components/Money";
import { WarningsBanner } from "@/components/WarningsBanner";
import type { Product } from "@/lib/types";

export default function ProductsPage() {
  const { t } = useLocale();
  const [editing, setEditing] = useState<Product | null>(null);
  const [sku, setSku] = useState("");
  const [name, setName] = useState("");
  const [unitPrice, setUnitPrice] = useState("");
  const [taxRate, setTaxRate] = useState("0");
  const [error, setError] = useState<string | null>(null);
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});
  const [refreshToken, setRefreshToken] = useState(0);

  const startEdit = (product: Product) => {
    setEditing(product);
    setSku(product.sku);
    setName(product.name);
    setUnitPrice(product.unit_price);
    setTaxRate(product.tax_rate);
  };

  const cancelEdit = () => {
    setEditing(null);
    setSku("");
    setName("");
    setUnitPrice("");
    setTaxRate("0");
    setError(null);
    setFieldErr({});
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setFieldErr({});
    const payload = { sku, name, unit_price: unitPrice, tax_rate: taxRate };
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
      <h1>{t("products")}</h1>
      <div className="card">
        <form onSubmit={onSubmit} style={{ display: "flex", gap: "0.75rem", alignItems: "end", flexWrap: "wrap" }}>
          <FormField name="sku" label={t("sku")} required error={fieldErr.sku}>
            <input value={sku} onChange={(e) => setSku(e.target.value)} required />
          </FormField>
          <FormField name="name" label={t("name")} required error={fieldErr.name}>
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </FormField>
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

      <DataTable<Product>
        endpoint="/products/"
        refreshToken={refreshToken}
        onEdit={startEdit}
        columns={[
          { key: "sku", label: t("sku"), sortable: true },
          { key: "name", label: t("name"), sortable: true },
          { key: "unit_price", label: t("unitPrice"), sortable: true, render: (row) => <Money amount={row.unit_price} /> },
          { key: "tax_rate", label: t("taxRate") },
        ]}
      />
    </div>
  );
}
