"use client";

import { useEffect, useState } from "react";
import { api, fieldErrors, generalError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import { FormField } from "@/components/FormField";
import { ItemPicker } from "@/components/ItemPicker";
import { WarningsBanner } from "@/components/WarningsBanner";
import { flattenLeafAccounts, type FlatAccountOption } from "@/lib/accounts";
import type {
  AccountTreeNode, CostCenter, ItemUoM, LegalEntity, Paginated, Party, Product, StockDocument,
  StockDocumentKind, UnitOfMeasure, Warehouse,
} from "@/lib/types";

interface LineDraft {
  item: Product | null;
  uom: string;
  qty: string;
  unitCost: string;
  costCenter: string;
  batchNumber: string;
  batchExpiry: string;
  serials: string;
}

const EMPTY_LINE: LineDraft = {
  item: null, uom: "", qty: "", unitCost: "", costCenter: "", batchNumber: "", batchExpiry: "", serials: "",
};

interface Destination {
  id: string;
  code: string;
  name: string;
  legal_entity_name: string;
}

function splitSerials(text: string): string[] {
  return text.split(/[\n,;\t]+/).map((s) => s.trim()).filter(Boolean);
}

/** Sprint 7.4: header + lines for إذن إضافة/صرف/تحويل, new or a DRAFT
 * being edited (same full-replace shape as VoucherScreen's lines). Sends
 * only what the user entered — quantities in base units, line values and
 * totals are all computed by the server. */
export function StockDocumentForm({
  kind,
  document,
  onSaved,
  onCancel,
}: {
  kind: StockDocumentKind;
  document?: StockDocument;
  onSaved: (doc: StockDocument) => void;
  onCancel?: () => void;
}) {
  const { t } = useLocale();
  const { me } = useAuth();
  const isReceipt = kind === "receipt";
  const isTransfer = kind === "transfer";
  const showCostCenterUI = !!me && me.features.cost_centers;

  const [entities, setEntities] = useState<LegalEntity[]>([]);
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [destinations, setDestinations] = useState<Destination[]>([]);
  const [parties, setParties] = useState<Party[]>([]);
  const [accounts, setAccounts] = useState<FlatAccountOption[]>([]);
  const [costCenters, setCostCenters] = useState<CostCenter[]>([]);
  const [units, setUnits] = useState<UnitOfMeasure[]>([]);
  const [itemUoms, setItemUoms] = useState<Record<string, ItemUoM[]>>({});

  const [legalEntityId, setLegalEntityId] = useState(document?.legal_entity ?? "");
  const [warehouseId, setWarehouseId] = useState(document?.warehouse ?? "");
  const [toWarehouseId, setToWarehouseId] = useState(document?.to_warehouse ?? "");
  const [date, setDate] = useState(document?.date ?? new Date().toISOString().slice(0, 10));
  const [reference, setReference] = useState(document?.reference ?? "");
  const [partyId, setPartyId] = useState(document?.party ?? "");
  const [accountId, setAccountId] = useState(document?.account ?? "");
  const [notes, setNotes] = useState(document?.notes ?? "");
  const [lines, setLines] = useState<LineDraft[]>([{ ...EMPTY_LINE }]);
  const [error, setError] = useState<string | null>(null);
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    (async () => {
      const [entityData, warehouseData, partyData, tree, unitData] = await Promise.all([
        api.get<Paginated<LegalEntity>>("/legal-entities/"),
        api.get<Paginated<Warehouse>>("/warehouses/"),
        api.get<Paginated<Party>>("/parties/"),
        isTransfer ? Promise.resolve([] as AccountTreeNode[]) : api.get<AccountTreeNode[]>("/accounts/tree/"),
        api.get<Paginated<UnitOfMeasure>>("/inventory/units/"),
      ]);
      const usable = entityData.results.filter((e) => e.entity_type !== "holding");
      setEntities(usable);
      setWarehouses(warehouseData.results);
      setParties(partyData.results);
      setAccounts(flattenLeafAccounts(tree));
      setUnits(unitData.results);
      if (!document) {
        if (usable.length === 1) setLegalEntityId((prev) => prev || usable[0].id);
        else if (me?.default_legal_entity_id) setLegalEntityId((prev) => prev || me.default_legal_entity_id!);
      }
      if (showCostCenterUI) {
        const ccData = await api.get<Paginated<CostCenter>>("/cost-centers/");
        setCostCenters(ccData.results);
      }
      if (document) {
        // Editing a draft: rebuild line drafts with the full Product rows
        // (the picker shows code — name, and tracking drives the fields).
        const items = await Promise.all(
          document.lines.map((line) => api.get<Product>(`/products/${line.item}/`)),
        );
        setLines(
          document.lines.map((line, i) => ({
            item: items[i], uom: line.uom ?? "", qty: line.qty, unitCost: line.unit_cost,
            costCenter: line.cost_center ?? "", batchNumber: line.batch_number ?? "",
            batchExpiry: line.batch_expiry ?? "", serials: line.serial_numbers.join("\n"),
          })),
        );
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!isTransfer || !warehouseId) {
      setDestinations([]);
      return;
    }
    api
      .get<Destination[]>(`/stock-documents/transfer-destinations/?warehouse=${warehouseId}`)
      .then(setDestinations);
  }, [isTransfer, warehouseId]);

  const entityWarehouses = warehouses.filter((w) => !legalEntityId || w.legal_entity === legalEntityId);

  const loadUoms = (item: Product | null) => {
    if (!item || itemUoms[item.id]) return;
    api
      .get<Paginated<ItemUoM>>(`/inventory/item-uoms/?item=${item.id}`)
      .then((data) => setItemUoms((prev) => ({ ...prev, [item.id]: data.results })));
  };

  const updateLine = (index: number, patch: Partial<LineDraft>) => {
    setLines((prev) => prev.map((line, i) => (i === index ? { ...line, ...patch } : line)));
  };

  const duplicateSerial = (): string | null => {
    const seen = new Set<string>();
    for (const line of lines) {
      if (!line.item) continue;
      for (const serial of splitSerials(line.serials)) {
        const key = `${line.item.id}:${serial}`;
        if (seen.has(key)) return serial;
        seen.add(key);
      }
    }
    return null;
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setFieldErr({});
    const dup = duplicateSerial();
    if (dup) {
      setError(t("stockSerialDuplicate").replace("{serial}", dup));
      return;
    }
    const payload = {
      kind,
      legal_entity: legalEntityId,
      warehouse: warehouseId,
      ...(isTransfer ? { to_warehouse: toWarehouseId } : {}),
      date,
      reference,
      notes,
      party: partyId || null,
      ...(isTransfer ? {} : { account: accountId || null }),
      lines: lines
        .filter((l) => l.item && l.qty)
        .map((l) => ({
          item: l.item!.id,
          qty: l.qty,
          ...(l.uom ? { uom: l.uom } : {}),
          ...(isReceipt ? { unit_cost: l.unitCost || "0" } : {}),
          ...(l.costCenter ? { cost_center: l.costCenter } : {}),
          ...(l.batchNumber ? { batch_number: l.batchNumber } : {}),
          ...(isReceipt && l.batchExpiry ? { batch_expiry: l.batchExpiry } : {}),
          serials: splitSerials(l.serials),
        })),
    };
    setSaving(true);
    try {
      const saved = document
        ? await api.patch<StockDocument>(`/stock-documents/${document.id}/`, payload)
        : await api.post<StockDocument>("/stock-documents/", payload);
      onSaved(saved);
      if (!document) {
        setLines([{ ...EMPTY_LINE }]);
        setReference("");
        setNotes("");
      }
    } catch (err) {
      setFieldErr(fieldErrors((err as { body?: unknown }).body));
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave"), (err as { status?: number }).status));
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={onSubmit}>
      <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
        {entities.length > 1 && (
          <FormField name="legal_entity" required error={fieldErr.legal_entity} style={{ minWidth: "220px" }}>
            <select
              value={legalEntityId}
              onChange={(e) => { setLegalEntityId(e.target.value); setWarehouseId(""); setToWarehouseId(""); }}
              required
            >
              <option value="" disabled>—</option>
              {entities.map((entity) => (
                <option key={entity.id} value={entity.id}>{entity.code} — {entity.name}</option>
              ))}
            </select>
          </FormField>
        )}
        <FormField
          name="warehouse" label={isTransfer ? t("stockFromWarehouse") : t("warehouse")} required
          error={fieldErr.warehouse} style={{ minWidth: "200px" }}
        >
          <select value={warehouseId} onChange={(e) => { setWarehouseId(e.target.value); setToWarehouseId(""); }} required>
            <option value="" disabled>—</option>
            {entityWarehouses.map((w) => (
              <option key={w.id} value={w.id}>{w.code} — {w.name}</option>
            ))}
          </select>
        </FormField>
        {isTransfer && (
          <FormField name="to_warehouse" label={t("stockToWarehouse")} required error={fieldErr.to_warehouse} style={{ minWidth: "220px" }}>
            <select value={toWarehouseId} onChange={(e) => setToWarehouseId(e.target.value)} required disabled={!warehouseId}>
              <option value="" disabled>—</option>
              {destinations.map((w) => (
                <option key={w.id} value={w.id}>{w.code} — {w.name} ({w.legal_entity_name})</option>
              ))}
            </select>
          </FormField>
        )}
        <FormField name="date" label={t("stockDocDate")} required error={fieldErr.date}>
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
        </FormField>
        <FormField name="reference" error={fieldErr.reference}>
          <input value={reference} onChange={(e) => setReference(e.target.value)} />
        </FormField>
        <FormField name="party" label={t("stockParty")} error={fieldErr.party} style={{ minWidth: "200px" }}>
          <select value={partyId} onChange={(e) => setPartyId(e.target.value)}>
            <option value="">{t("none")}</option>
            {parties.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </FormField>
        {!isTransfer && (
          <FormField
            name="account" label={t(isReceipt ? "stockCounterAccountReceipt" : "stockCounterAccountIssue")}
            error={fieldErr.account} style={{ minWidth: "260px" }}
          >
            <select value={accountId} onChange={(e) => setAccountId(e.target.value)}>
              <option value="">—</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>{a.label}</option>
              ))}
            </select>
          </FormField>
        )}
        <FormField name="notes" error={fieldErr.notes} style={{ flex: 1, minWidth: "220px" }}>
          <input value={notes} onChange={(e) => setNotes(e.target.value)} />
        </FormField>
      </div>

      <h4 style={{ marginTop: "1rem" }}>{t("stockItem")}</h4>
      {lines.map((line, i) => {
        const tracking = line.item?.tracking;
        const uomOptions = line.item ? itemUoms[line.item.id] ?? [] : [];
        return (
          <div key={i} className="card" style={{ padding: "0.6rem", marginBottom: "0.5rem" }}>
            <div style={{ display: "flex", gap: "0.75rem", alignItems: "end", flexWrap: "wrap" }}>
              <FormField name={`lines.${i}.item`} label={t("stockItem")} required>
                <ItemPicker
                  value={line.item}
                  required
                  onChange={(item) => { updateLine(i, { item, uom: "" }); loadUoms(item); }}
                />
              </FormField>
              <FormField name={`lines.${i}.uom`} label={t("stockUnit")} style={{ minWidth: "120px" }}>
                <select value={line.uom} onChange={(e) => updateLine(i, { uom: e.target.value })}>
                  <option value="">{t("stockBaseUnit")}</option>
                  {uomOptions.map((u) => (
                    <option key={u.id} value={u.uom}>
                      {units.find((unit) => unit.id === u.uom)?.name_ar ?? u.uom} (×{u.factor_to_base})
                    </option>
                  ))}
                </select>
              </FormField>
              <FormField name={`lines.${i}.qty`} label={t("quantity")} required style={{ width: "110px" }}>
                <input type="number" step="0.01" min="0.01" value={line.qty} onChange={(e) => updateLine(i, { qty: e.target.value })} required />
              </FormField>
              {isReceipt && (
                <FormField name={`lines.${i}.unit_cost`} label={t("stockUnitCost")} required style={{ width: "130px" }}>
                  <input type="number" step="0.01" min="0" value={line.unitCost} onChange={(e) => updateLine(i, { unitCost: e.target.value })} required />
                </FormField>
              )}
              {showCostCenterUI && (
                <FormField name={`lines.${i}.cost_center`} label={t("costCenter")} style={{ minWidth: "160px" }}>
                  <select value={line.costCenter} onChange={(e) => updateLine(i, { costCenter: e.target.value })}>
                    <option value="">{t("none")}</option>
                    {costCenters.map((cc) => (
                      <option key={cc.id} value={cc.id}>{cc.code} — {cc.name}</option>
                    ))}
                  </select>
                </FormField>
              )}
              {tracking === "batch" && (
                <>
                  <FormField name={`lines.${i}.batch_number`} label={t("stockBatchNumber")} required style={{ width: "140px" }}>
                    <input value={line.batchNumber} onChange={(e) => updateLine(i, { batchNumber: e.target.value })} required />
                  </FormField>
                  {isReceipt && (
                    <FormField name={`lines.${i}.batch_expiry`} label={t("stockExpiry")}>
                      <input type="date" value={line.batchExpiry} onChange={(e) => updateLine(i, { batchExpiry: e.target.value })} />
                    </FormField>
                  )}
                </>
              )}
              {lines.length > 1 && (
                <button type="button" className="secondary" onClick={() => setLines(lines.filter((_, j) => j !== i))}>×</button>
              )}
            </div>
            {tracking === "serial" && (
              <FormField name={`lines.${i}.serials`} label={t("stockSerials")} hint={t("stockSerialsHint")} style={{ marginTop: "0.5rem" }}>
                <textarea rows={3} value={line.serials} onChange={(e) => updateLine(i, { serials: e.target.value })} />
              </FormField>
            )}
          </div>
        );
      })}
      <button type="button" className="secondary" onClick={() => setLines([...lines, { ...EMPTY_LINE }])} style={{ marginBottom: "1rem" }}>
        {t("addLine")}
      </button>
      <br />
      <WarningsBanner warnings={error ? [error] : []} variant="error" />
      <button className="primary" type="submit" disabled={saving}>{t("stockSaveDraft")}</button>
      {onCancel && (
        <button type="button" className="secondary" style={{ marginInlineStart: "0.5rem" }} onClick={onCancel}>
          {t("cancel")}
        </button>
      )}
    </form>
  );
}
