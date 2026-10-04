"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, fieldErrors, generalError } from "@/lib/api";
import { flattenLeafAccounts, type FlatAccountOption } from "@/lib/accounts";
import { useLocale } from "@/lib/i18n";
import { ChangeHistoryTab } from "@/components/ChangeHistoryTab";
import { FormField } from "@/components/FormField";
import { WarningsBanner } from "@/components/WarningsBanner";
import type {
  AccountTreeNode,
  ItemBarcode,
  ItemCategory,
  ItemTracking,
  ItemType,
  ItemUoM,
  Paginated,
  PricingMode,
  Product,
  UnitOfMeasure,
} from "@/lib/types";

export default function ProductDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { t } = useLocale();

  const [item, setItem] = useState<Product | null>(null);
  const [categories, setCategories] = useState<ItemCategory[]>([]);
  const [units, setUnits] = useState<UnitOfMeasure[]>([]);
  const [accounts, setAccounts] = useState<FlatAccountOption[]>([]);
  const [uoms, setUoms] = useState<ItemUoM[]>([]);
  const [barcodes, setBarcodes] = useState<ItemBarcode[]>([]);

  const [error, setError] = useState<string | null>(null);
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});

  const [newUom, setNewUom] = useState("");
  const [newFactor, setNewFactor] = useState("");
  const [uomError, setUomError] = useState<string | null>(null);

  const [newBarcode, setNewBarcode] = useState("");
  const [newBarcodeUom, setNewBarcodeUom] = useState("");
  const [barcodeError, setBarcodeError] = useState<string | null>(null);

  const load = () => {
    Promise.all([
      api.get<Product>(`/products/${id}/`),
      api.get<Paginated<ItemCategory>>("/inventory/item-categories/?page_size=200"),
      api.get<Paginated<UnitOfMeasure>>("/inventory/units/?page_size=200"),
      api.get<AccountTreeNode[]>("/accounts/tree/"),
      api.get<Paginated<ItemUoM>>(`/inventory/item-uoms/?item=${id}`),
      api.get<Paginated<ItemBarcode>>(`/inventory/item-barcodes/?item=${id}`),
    ]).then(([itemData, catData, unitData, accountTree, uomData, barcodeData]) => {
      setItem(itemData);
      setCategories(catData.results);
      setUnits(unitData.results);
      setAccounts(flattenLeafAccounts(accountTree));
      setUoms(uomData.results);
      setBarcodes(barcodeData.results);
    });
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (!item) return null;

  const patch = async (payload: Partial<Product>) => {
    setError(null);
    setFieldErr({});
    try {
      const updated = await api.patch<Product>(`/products/${id}/`, payload);
      setItem(updated);
    } catch (err) {
      setFieldErr(fieldErrors((err as { body?: unknown }).body));
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const addUom = async (e: React.FormEvent) => {
    e.preventDefault();
    setUomError(null);
    try {
      await api.post("/inventory/item-uoms/", { item: id, uom: newUom, factor_to_base: newFactor });
      setNewUom("");
      setNewFactor("");
      load();
    } catch (err) {
      setUomError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const addBarcode = async (e: React.FormEvent) => {
    e.preventDefault();
    setBarcodeError(null);
    try {
      await api.post("/inventory/item-barcodes/", { item: id, barcode: newBarcode, uom: newBarcodeUom || null });
      setNewBarcode("");
      setNewBarcodeUom("");
      load();
    } catch (err) {
      setBarcodeError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  return (
    <div>
      <button className="secondary" onClick={() => router.push("/dashboard/products")}>
        ← {t("back")}
      </button>

      <h1 style={{ marginTop: "1rem" }}>{item.name}</h1>
      <p style={{ color: "var(--muted)" }}>{item.sku}</p>

      <WarningsBanner warnings={error ? [error] : []} variant="error" />

      {/* تبويب: بيانات */}
      <div className="card">
        <h3>{t("itemDataTab")}</h3>
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
          <FormField name="name" label={t("name")} error={fieldErr.name}>
            <input defaultValue={item.name} onBlur={(e) => e.target.value !== item.name && patch({ name: e.target.value })} />
          </FormField>
          <FormField name="item_type" label={t("itemType")} error={fieldErr.item_type}>
            <select value={item.item_type} onChange={(e) => patch({ item_type: e.target.value as ItemType })}>
              <option value="service">{t("itemTypeService")}</option>
              <option value="stock">{t("itemTypeStock")}</option>
            </select>
          </FormField>
          <FormField name="category" label={t("category")} error={fieldErr.category}>
            <select value={item.category || ""} onChange={(e) => patch({ category: e.target.value || null })}>
              <option value="">{t("noCategory")}</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.code} {c.name}
                </option>
              ))}
            </select>
          </FormField>
          <FormField name="unit_price" label={t("unitPrice")} error={fieldErr.unit_price}>
            <input
              type="number" step="0.01" defaultValue={item.unit_price} // money-ok: editable numeric input, not a display
              onBlur={(e) => e.target.value !== item.unit_price && patch({ unit_price: e.target.value })}
            />
          </FormField>
          <FormField name="tax_rate" label={t("taxRate")} error={fieldErr.tax_rate}>
            <input
              type="number" step="0.01" defaultValue={item.tax_rate}
              onBlur={(e) => e.target.value !== item.tax_rate && patch({ tax_rate: e.target.value })}
            />
          </FormField>
          <FormField name="part_number" label={t("partNumber")} error={fieldErr.part_number}>
            <input
              defaultValue={item.part_number} onBlur={(e) => e.target.value !== item.part_number && patch({ part_number: e.target.value })}
            />
          </FormField>
          <FormField name="pricing_mode" label={t("pricingMode")} error={fieldErr.pricing_mode}>
            <select value={item.pricing_mode} onChange={(e) => patch({ pricing_mode: e.target.value as PricingMode })}>
              <option value="fixed">{t("pricingModeFixed")}</option>
              <option value="weight_rate">{t("pricingModeWeightRate")}</option>
            </select>
          </FormField>
          <label style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
            <input type="checkbox" checked={item.is_bundle} onChange={(e) => patch({ is_bundle: e.target.checked })} /* form-ok: checkbox label-wraps-input, FormField's layout doesn't fit */ />
            {t("isBundle")}
          </label>
        </div>
      </div>

      {/* تبويب: الوحدات والباركود */}
      <div className="card">
        <h3>{t("itemUnitsBarcodeTab")}</h3>
        <FormField name="base_uom" label={t("baseUom")} error={fieldErr.base_uom}>
          <select value={item.base_uom || ""} onChange={(e) => patch({ base_uom: e.target.value || null })}>
            <option value="">—</option>
            {units.map((u) => (
              <option key={u.id} value={u.id}>
                {u.code} {u.name_ar}
              </option>
            ))}
          </select>
        </FormField>

        <h4 style={{ marginTop: "1rem" }}>{t("alternateUnits")}</h4>
        <table>
          <thead>
            <tr>
              <th>{t("unitsOfMeasure")}</th>
              <th>{t("factorToBase")}</th>
            </tr>
          </thead>
          <tbody>
            {uoms.map((u) => (
              <tr key={u.id}>
                <td>{units.find((x) => x.id === u.uom)?.name_ar ?? u.uom}</td>
                <td>{u.factor_to_base}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <form onSubmit={addUom} style={{ display: "flex", gap: "0.5rem", alignItems: "end", marginTop: "0.5rem" }}>
          <FormField name="uom" label={t("unitsOfMeasure")}>
            <select value={newUom} onChange={(e) => setNewUom(e.target.value)} required>
              <option value="">—</option>
              {units.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.code} {u.name_ar}
                </option>
              ))}
            </select>
          </FormField>
          <FormField name="factor_to_base" label={t("factorToBase")}>
            <input type="number" step="0.01" value={newFactor} onChange={(e) => setNewFactor(e.target.value)} required />
          </FormField>
          <button className="secondary" type="submit">
            {t("addUnit")}
          </button>
        </form>
        <WarningsBanner warnings={uomError ? [uomError] : []} variant="error" />

        <h4 style={{ marginTop: "1rem" }}>{t("barcodes")}</h4>
        <table>
          <thead>
            <tr>
              <th>{t("barcode")}</th>
              <th>{t("unitsOfMeasure")}</th>
            </tr>
          </thead>
          <tbody>
            {barcodes.map((b) => (
              <tr key={b.id}>
                <td>{b.barcode}</td>
                <td>{b.uom ? units.find((x) => x.id === b.uom)?.name_ar ?? b.uom : t("baseUom")}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <form onSubmit={addBarcode} style={{ display: "flex", gap: "0.5rem", alignItems: "end", marginTop: "0.5rem" }}>
          <FormField name="barcode" label={t("barcode")}>
            <input value={newBarcode} onChange={(e) => setNewBarcode(e.target.value)} required />
          </FormField>
          <FormField name="uom" label={t("unitsOfMeasure")}>
            <select value={newBarcodeUom} onChange={(e) => setNewBarcodeUom(e.target.value)}>
              <option value="">{t("baseUom")}</option>
              {units.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.code} {u.name_ar}
                </option>
              ))}
            </select>
          </FormField>
          <button className="secondary" type="submit">
            {t("addBarcode")}
          </button>
        </form>
        <WarningsBanner warnings={barcodeError ? [barcodeError] : []} variant="error" />
      </div>

      {/* تبويب: التتبع والصلاحية */}
      <div className="card">
        <h3>{t("itemTrackingPermissionTab")}</h3>
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
          <FormField name="tracking" label={t("tracking")} error={fieldErr.tracking}>
            <select
              value={item.tracking}
              onChange={(e) => patch({ tracking: e.target.value as ItemTracking })}
              disabled={item.item_type === "service"}
            >
              <option value="">—</option>
              <option value="none">{t("trackingNone")}</option>
              <option value="serial">{t("trackingSerial")}</option>
              <option value="batch">{t("trackingBatch")}</option>
            </select>
          </FormField>
          <label style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
            <input type="checkbox" checked={item.expiry_required} onChange={(e) => patch({ expiry_required: e.target.checked })} /* form-ok: checkbox label-wraps-input, FormField's layout doesn't fit */ />
            {t("expiryRequired")}
          </label>
          <FormField name="reorder_level" label={t("reorderLevel")} error={fieldErr.reorder_level}>
            <input
              type="number" step="0.01" defaultValue={item.reorder_level ?? ""}
              onBlur={(e) => patch({ reorder_level: e.target.value || null })}
            />
          </FormField>
        </div>
      </div>

      {/* تبويب: الحسابات (متقدم مطوي) */}
      <details className="card">
        <summary style={{ cursor: "pointer" }}>
          <h3 style={{ display: "inline" }}>{t("itemAccountsTab")}</h3>
        </summary>
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
          <FormField name="inventory_account_override" label={t("inventoryAccountOverride")} error={fieldErr.inventory_account_override}>
            <select value={item.inventory_account_override || ""} onChange={(e) => patch({ inventory_account_override: e.target.value || null })}>
              <option value="">—</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.label}
                </option>
              ))}
            </select>
          </FormField>
          <FormField name="cogs_account_override" label={t("cogsAccountOverride")} error={fieldErr.cogs_account_override}>
            <select value={item.cogs_account_override || ""} onChange={(e) => patch({ cogs_account_override: e.target.value || null })}>
              <option value="">—</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.label}
                </option>
              ))}
            </select>
          </FormField>
          <FormField name="purchase_cost_default" label={t("purchaseCostDefault")} error={fieldErr.purchase_cost_default}>
            <input
              type="number" step="0.01" defaultValue={item.purchase_cost_default ?? ""}
              onBlur={(e) => patch({ purchase_cost_default: e.target.value || null })}
            />
          </FormField>
          <FormField name="metal" label={t("metal")} error={fieldErr.metal}>
            <input defaultValue={item.metal} onBlur={(e) => e.target.value !== item.metal && patch({ metal: e.target.value })} />
          </FormField>
          <FormField name="karat" label={t("karat")} error={fieldErr.karat}>
            <input type="number" defaultValue={item.karat ?? ""} onBlur={(e) => patch({ karat: e.target.value ? Number(e.target.value) : null })} />
          </FormField>
          <FormField name="weight_grams" label={t("weightGrams")} error={fieldErr.weight_grams}>
            <input
              type="number" step="0.001" defaultValue={item.weight_grams ?? ""}
              onBlur={(e) => patch({ weight_grams: e.target.value || null })}
            />
          </FormField>
          <FormField name="making_charge_per_gram" label={t("makingChargePerGram")} error={fieldErr.making_charge_per_gram}>
            <input
              type="number" step="0.01" defaultValue={item.making_charge_per_gram ?? ""}
              onBlur={(e) => patch({ making_charge_per_gram: e.target.value || null })}
            />
          </FormField>
        </div>
      </details>

      {/* تبويبا الأرصدة والحركات — 7.3/7.10 */}
      <div className="card">
        <h3>{t("itemBalancesTab")}</h3>
        <p style={{ color: "var(--muted)" }}>{t("comingInLaterBlock")}</p>
      </div>
      <div className="card">
        <h3>{t("itemMovementsTab")}</h3>
        <p style={{ color: "var(--muted)" }}>{t("comingInLaterBlock")}</p>
      </div>

      <ChangeHistoryTab targetType="sales.product" targetId={item.id} />
    </div>
  );
}
