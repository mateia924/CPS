"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, generalError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { Money } from "@/components/Money";
import { StatusBadge } from "@/components/StatusBadge";
import { StockDocumentForm } from "@/components/StockDocumentForm";
import { WarningsBanner } from "@/components/WarningsBanner";
import { formatDate } from "@/lib/date";
import type { LegalEntity, Paginated, StockDocument, StockDocumentKind, Warehouse } from "@/lib/types";
import { ErrorState, apiErrorKind, type ApiErrorKind } from "@/components/ScreenErrors";

export const STOCK_KIND_SLUG: Record<StockDocumentKind, string> = {
  receipt: "receipts",
  issue: "issues",
  transfer: "transfers",
  count: "counts",
};

const TITLE: Record<StockDocumentKind, string> = {
  receipt: "stockReceipts",
  issue: "stockIssues",
  transfer: "stockTransfers",
  count: "stockCounts",
};

const NEW_TITLE: Record<StockDocumentKind, string> = {
  receipt: "newStockReceipt",
  issue: "newStockIssue",
  transfer: "newStockTransfer",
  count: "newStockCount",
};

const STATUSES = ["draft", "pending_approval", "approved", "posted", "reversed"] as const;

/** Sprint 7.4: one screen per kind (إذن إضافة / صرف / تحويل), same shape
 * as VoucherScreen: the new-document form on top, the filtered list
 * below. The transfer screen also carries «تحويلات واردة بانتظار
 * التأكيد» for the receiving branch. Actions live on the detail screen;
 * the API enforces every one of them regardless of what is shown here. */
export function StockDocumentScreen({ kind }: { kind: StockDocumentKind }) {
  const { t } = useLocale();
  const { hasPermission } = useAuth();
  const router = useRouter();
  const canCreate = hasPermission("inventory.manage");
  const canPost = hasPermission("inventory.post");

  const [entities, setEntities] = useState<LegalEntity[]>([]);
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [listEntityId, setListEntityId] = useState("");
  const [status, setStatus] = useState("");
  const [warehouseId, setWarehouseId] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [refreshToken, setRefreshToken] = useState(0);
  const [incoming, setIncoming] = useState<StockDocument[]>([]);
  // Block 8.0.2: a failed load must not read «لا توجد تحويلات واردة».
  const [incomingError, setIncomingError] = useState<ApiErrorKind | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<Paginated<LegalEntity>>("/legal-entities/").then((d) =>
      setEntities(d.results.filter((e) => e.entity_type !== "holding")),
    );
    api.get<Paginated<Warehouse>>("/warehouses/").then((d) => setWarehouses(d.results));
  }, []);

  const loadIncoming = () => {
    if (kind !== "transfer") return;
    api
      .get<StockDocument[]>("/stock-documents/incoming/")
      .then((data) => {
        setIncoming(data);
        setIncomingError(null);
      })
      .catch((err) => {
        setIncoming([]);
        setIncomingError(apiErrorKind(err) ?? "server-error");
      });
  };
  useEffect(loadIncoming, [kind, refreshToken]);

  const confirmReceipt = async (doc: StockDocument) => {
    setError(null);
    try {
      await api.post(`/stock-documents/${doc.id}/confirm-receipt/`, {});
      setRefreshToken((n) => n + 1);
    } catch (err) {
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave"), (err as { status?: number }).status));
    }
  };

  return (
    <div>
      <h1>{t(TITLE[kind])}</h1>
      <WarningsBanner warnings={error ? [error] : []} variant="error" />

      {kind === "transfer" && (
        <div className="card" data-testid="incoming-transfers">
          <h3>{t("stockIncomingTransfers")}</h3>
          {incomingError ? (
            <ErrorState kind={incomingError} compact />
          ) : incoming.length === 0 ? (
            <p style={{ color: "var(--muted)" }}>{t("stockNoIncoming")}</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>{t("number")}</th>
                  <th>{t("date")}</th>
                  <th>{t("stockFromWarehouse")}</th>
                  <th>{t("stockToWarehouse")}</th>
                  <th>{t("stockTotalQty")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {incoming.map((doc) => (
                  <tr key={doc.id}>
                    <td><Link href={`/dashboard/inventory/stock/${doc.id}`}>{doc.number}</Link></td>
                    <td>{formatDate(doc.date, "form")}</td>
                    <td>{doc.warehouse_name} ({doc.legal_entity_name})</td>
                    <td>{doc.to_warehouse_name}</td>
                    <td><span className="money">{doc.total_qty}</span></td>
                    <td>
                      {canPost && (
                        <button className="primary" onClick={() => confirmReceipt(doc)}>{t("stockConfirmReceipt")}</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {canCreate && (
        <div className="card">
          <h3>{t(NEW_TITLE[kind])}</h3>
          <StockDocumentForm kind={kind} onSaved={(doc) => router.push(`/dashboard/inventory/stock/${doc.id}`)} />
        </div>
      )}

      <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
        <FormField name="list_entity_filter" label={t("entityFilter")}>
          <select value={listEntityId} onChange={(e) => setListEntityId(e.target.value)}>
            <option value="">{t("allEntities")}</option>
            {entities.map((entity) => (
              <option key={entity.id} value={entity.id}>{entity.code} — {entity.name}</option>
            ))}
          </select>
        </FormField>
        <FormField name="status_filter" label={t("status")}>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("stockAllStatuses")}</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>{t(s)}</option>
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
        <FormField name="date_from" label={t("dateFrom")}>
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </FormField>
        <FormField name="date_to" label={t("dateTo")}>
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </FormField>
      </div>

      <DataTable<StockDocument>
        endpoint="/stock-documents/"
        extraParams={{
          kind, legal_entity: listEntityId, status, warehouse: warehouseId, date_from: dateFrom, date_to: dateTo,
        }}
        refreshToken={refreshToken}
        hasActiveToggle={false}
        columns={[
          { key: "number", label: t("number"), render: (row) => row.number || `(${t("draft")})` },
          { key: "date", label: t("date"), render: (row) => formatDate(row.date, "form") },
          { key: "legal_entity_name", label: t("legalEntity") },
          {
            key: "warehouse_name", label: kind === "transfer" ? t("stockFromWarehouse") : t("warehouse"),
          },
          ...(kind === "transfer"
            ? [{ key: "to_warehouse_name", label: t("stockToWarehouse") }]
            : []),
          {
            key: "total_value", label: t("stockTotalValue"),
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
