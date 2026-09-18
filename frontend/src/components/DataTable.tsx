"use client";

import { useCallback, useEffect, useState } from "react";
import { api as customerApi } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import type { Paginated } from "@/lib/types";

interface ApiClient {
  get: <T>(path: string) => Promise<T>;
  post: <T>(path: string, body?: unknown) => Promise<T>;
}

const PAGE_SIZE = 25; // matches backend REST_FRAMEWORK.PAGE_SIZE

export interface DataTableColumn<T> {
  key: string;
  label: string;
  render?: (row: T) => React.ReactNode;
  sortable?: boolean;
}

export interface DataTableRow {
  id: string;
  is_active?: boolean;
}

interface DataTableProps<T extends DataTableRow> {
  /** API path, e.g. "/customers/" — must end with a slash. */
  endpoint: string;
  columns: DataTableColumn<T>[];
  onEdit?: (row: T) => void;
  /** Per-row gate on top of `onEdit` — e.g. an issued invoice can't be
   * edited even though the column itself supports editing in general. */
  canEdit?: (row: T) => boolean;
  /** Whether this resource has deactivate/activate + a "show disabled"
   * filter (customers/products/legal entities/cost centers/users do;
   * invoices use status instead and set this to false). */
  hasActiveToggle?: boolean;
  /** Extra per-row action buttons (e.g. invoice issue/void). Receives a
   * `reload` callback to refresh the table after the action completes. */
  renderExtraActions?: (row: T, reload: () => void) => React.ReactNode;
  emptyMessage?: string;
  /** Bump this (e.g. from a parent's useState counter) to force a reload
   * — typically after the "add" form outside this component succeeds. */
  refreshToken?: number;
  /** Which API client to call through — defaults to the customer-facing
   * `api` (cps_access token). The platform admin panel (sprint 2) passes
   * `platformApi` here instead, so this same component works against
   * both auth realms without any endpoint-specific branching. */
  api?: ApiClient;
  /** Extra fixed query params merged into every request (e.g. the
   * platform tenants screen's status/plan dropdown filters) — separate
   * from `search`, which stays a free-text box. */
  extraParams?: Record<string, string>;
}

export function DataTable<T extends DataTableRow>({
  endpoint,
  columns,
  onEdit,
  canEdit,
  hasActiveToggle = true,
  renderExtraActions,
  emptyMessage,
  refreshToken,
  api = customerApi,
  extraParams,
}: DataTableProps<T>) {
  const { t } = useLocale();
  const [rows, setRows] = useState<T[]>([]);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [ordering, setOrdering] = useState<string | null>(null);
  const [showInactive, setShowInactive] = useState(false);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const params = new URLSearchParams();
    params.set("page", String(page));
    if (search) params.set("search", search);
    if (ordering) params.set("ordering", ordering);
    if (hasActiveToggle && showInactive) params.set("show_inactive", "true");
    if (extraParams) {
      for (const [key, value] of Object.entries(extraParams)) {
        if (value) params.set(key, value);
      }
    }
    try {
      const data = await api.get<Paginated<T>>(`${endpoint}?${params.toString()}`);
      setRows(data.results);
      setCount(data.count);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endpoint, page, search, ordering, showInactive, hasActiveToggle, api, JSON.stringify(extraParams)]);

  useEffect(() => {
    setPage(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(extraParams)]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load, refreshToken]);

  const toggleSort = (key: string) => {
    setPage(1);
    setOrdering((prev) => (prev === key ? `-${key}` : key));
  };

  const toggleActive = async (row: T) => {
    const isActive = row.is_active ?? true;
    if (!window.confirm(isActive ? t("confirmDeactivate") : t("confirmActivate"))) return;
    await api.post(`${endpoint}${row.id}/${isActive ? "deactivate" : "activate"}/`);
    load();
  };

  const totalPages = Math.max(1, Math.ceil(count / PAGE_SIZE));
  const sortIndicator = (key: string) => {
    if (!ordering || ordering.replace("-", "") !== key) return "";
    return ordering.startsWith("-") ? " ▼" : " ▲";
  };

  return (
    <div>
      <div
        style={{
          display: "flex",
          gap: "0.75rem",
          marginBottom: "0.75rem",
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        <input
          placeholder={t("search")}
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
          style={{ padding: "0.5rem 0.7rem", border: "1px solid var(--border)", borderRadius: "8px" }}
        />
        {hasActiveToggle && (
          <label style={{ fontSize: "0.9rem", display: "flex", alignItems: "center", gap: "0.3rem" }}>
            <input
              type="checkbox"
              checked={showInactive}
              onChange={(e) => {
                setShowInactive(e.target.checked);
                setPage(1);
              }}
            />
            {t("showInactive")}
          </label>
        )}
      </div>

      <table>
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                onClick={col.sortable ? () => toggleSort(col.key) : undefined}
                style={col.sortable ? { cursor: "pointer" } : undefined}
              >
                {col.label}
                {col.sortable && sortIndicator(col.key)}
              </th>
            ))}
            <th></th>
          </tr>
        </thead>
        <tbody>
          {!loading && rows.length === 0 && (
            <tr>
              <td
                colSpan={columns.length + 1}
                style={{ textAlign: "center", padding: "2rem", color: "var(--muted)" }}
              >
                {emptyMessage || t("noData")}
              </td>
            </tr>
          )}
          {rows.map((row) => (
            <tr key={row.id} style={row.is_active === false ? { opacity: 0.55 } : undefined}>
              {columns.map((col) => (
                <td key={col.key}>{col.render ? col.render(row) : String((row as Record<string, unknown>)[col.key] ?? "")}</td>
              ))}
              <td style={{ whiteSpace: "nowrap" }}>
                {onEdit && (!canEdit || canEdit(row)) && (
                  <button className="secondary" onClick={() => onEdit(row)}>
                    {t("edit")}
                  </button>
                )}
                {hasActiveToggle && (
                  <button
                    className="secondary"
                    style={{ marginInlineStart: "0.4rem" }}
                    onClick={() => toggleActive(row)}
                  >
                    {(row.is_active ?? true) ? t("deactivate") : t("activate")}
                  </button>
                )}
                {renderExtraActions && (
                  <span style={{ marginInlineStart: "0.4rem" }}>{renderExtraActions(row, load)}</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {totalPages > 1 && (
        <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem", alignItems: "center" }}>
          <button className="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            ‹
          </button>
          <span>
            {page} / {totalPages}
          </span>
          <button className="secondary" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
            ›
          </button>
        </div>
      )}
    </div>
  );
}
