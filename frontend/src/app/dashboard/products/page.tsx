"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import type { Paginated, Product } from "@/lib/types";

export default function ProductsPage() {
  const { t } = useLocale();
  const [products, setProducts] = useState<Product[]>([]);
  const [sku, setSku] = useState("");
  const [name, setName] = useState("");
  const [unitPrice, setUnitPrice] = useState("");
  const [taxRate, setTaxRate] = useState("0");

  const load = async () => {
    const data = await api.get<Paginated<Product>>("/products/");
    setProducts(data.results);
  };

  useEffect(() => {
    load();
  }, []);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await api.post("/products/", {
      sku,
      name,
      unit_price: unitPrice,
      tax_rate: taxRate,
    });
    setSku("");
    setName("");
    setUnitPrice("");
    setTaxRate("0");
    load();
  };

  return (
    <div>
      <h1>{t("products")}</h1>
      <div className="card">
        <form onSubmit={onSubmit} style={{ display: "flex", gap: "0.75rem", alignItems: "end", flexWrap: "wrap" }}>
          <div className="form-field">
            <label>{t("sku")}</label>
            <input value={sku} onChange={(e) => setSku(e.target.value)} required />
          </div>
          <div className="form-field">
            <label>{t("name")}</label>
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="form-field">
            <label>{t("unitPrice")}</label>
            <input type="number" step="0.01" value={unitPrice} onChange={(e) => setUnitPrice(e.target.value)} required />
          </div>
          <div className="form-field">
            <label>{t("taxRate")}</label>
            <input type="number" step="0.01" value={taxRate} onChange={(e) => setTaxRate(e.target.value)} />
          </div>
          <button className="primary" type="submit">
            {t("add")}
          </button>
        </form>
      </div>
      <table>
        <thead>
          <tr>
            <th>{t("sku")}</th>
            <th>{t("name")}</th>
            <th>{t("unitPrice")}</th>
            <th>{t("taxRate")}</th>
          </tr>
        </thead>
        <tbody>
          {products.map((p) => (
            <tr key={p.id}>
              <td>{p.sku}</td>
              <td>{p.name}</td>
              <td>{p.unit_price}</td>
              <td>{p.tax_rate}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
