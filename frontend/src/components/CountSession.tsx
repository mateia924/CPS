"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, generalError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import { ChangeHistoryTab } from "@/components/ChangeHistoryTab";
import { FormField } from "@/components/FormField";
import { Money } from "@/components/Money";
import { StatusBadge } from "@/components/StatusBadge";
import { WarningsBanner } from "@/components/WarningsBanner";
import { formatDate } from "@/lib/date";
import type { AuditLogEntry, CountDrift, CountVariances, StockDocument } from "@/lib/types";

interface ImportError {
  row: number;
  reason: string;
}

function splitSerials(text: string): string[] {
  return text.split(/[\n,;\t ]+/).map((s) => s.trim()).filter(Boolean);
}

interface SurplusCostChange {
  item: string;
  sku: string;
  unit_cost: string | null;
}

/** «سجل التغييرات»: a surplus unit cost change, before -> after per item. */
function describeChange(entry: AuditLogEntry, atAverage: string): string | null {
  if (entry.action !== "stock_document.surplus_cost_set") return null;
  const before = (entry.before as { lines?: SurplusCostChange[] } | null)?.lines ?? [];
  const after = (entry.after as { lines?: SurplusCostChange[] } | null)?.lines ?? [];
  return after
    .map((a, i) => `${a.sku} — ${a.item}: ${before[i]?.unit_cost ?? atAverage} → ${a.unit_cost ?? atAverage}`)
    .join("؛ ");
}

function csvCell(value: string): string {
  return /[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

/** Sprint 7.5 (D16): one count session — «العدّ» (enter by hand or import
 * a CSV; DRAFT only) and «الفروق» (snapshot / balance now / counted /
 * variance / value, from the server). Posting goes through the API's
 * drift check: if a counted item's balance moved since the session
 * opened, the server answers 409 with the items, they are shown here, and
 * only an explicit second click posts — against the balance now. */
export function CountSession({ doc, reload }: { doc: StockDocument; reload: () => void }) {
  const router = useRouter();
  const { t } = useLocale();
  const { hasPermission, user } = useAuth();
  const canManage = hasPermission("inventory.manage");
  const canPost = hasPermission("inventory.post");
  const isDraft = doc.status === "draft";

  const [tab, setTab] = useState<"count" | "variances">(isDraft ? "count" : "variances");
  const [qty, setQty] = useState<Record<string, string>>({});
  const [serials, setSerials] = useState<Record<string, string>>({});
  const [costs, setCosts] = useState<Record<string, string>>({});
  const [findQuery, setFindQuery] = useState("");
  const [highlight, setHighlight] = useState<string | null>(null);
  const [variances, setVariances] = useState<CountVariances | null>(null);
  const [drift, setDrift] = useState<CountDrift[] | null>(null);
  const [importErrors, setImportErrors] = useState<ImportError[]>([]);
  const [reasonMode, setReasonMode] = useState<"reject" | "reverse" | null>(null);
  const [reasonText, setReasonText] = useState("");
  const [blind, setBlind] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setQty(Object.fromEntries(doc.lines.map((l) => [l.id, l.counted_qty ?? ""])));
    setSerials(Object.fromEntries(doc.lines.map((l) => [l.id, l.counted_serial_numbers.join("\n")])));
    setCosts(Object.fromEntries(doc.lines.map((l) => [l.id, l.surplus_unit_cost ?? ""])));
    api.get<CountVariances>(`/stock-documents/${doc.id}/variances/`).then(setVariances);
  }, [doc]);

  const fail = (err: unknown) =>
    setError(generalError((err as { body?: unknown }).body, t("couldNotSave"), (err as { status?: number }).status));

  const clearMessages = () => {
    setError(null);
    setNotice(null);
    setImportErrors([]);
  };

  const saveCounts = async () => {
    clearMessages();
    try {
      await api.post(`/stock-documents/${doc.id}/counts/`, {
        // Empty quantity and no serials = not counted; "0" = counted, none
        // found. A serial line's quantity may be left empty — the scanned
        // serials are the count.
        entries: doc.lines.map((line) => ({
          line: Number(line.id),
          counted_qty: qty[line.id] ?? "",
          serials: line.item_tracking === "serial" ? splitSerials(serials[line.id] ?? "") : [],
        })),
      });
      setNotice(t("stockCountsSaved"));
      reload();
    } catch (err) {
      const body = (err as { body?: { errors?: ImportError[] } }).body;
      if (body?.errors) setImportErrors(body.errors);
      fail(err);
    }
  };

  // «حاول الإضافة»: the server never adds a line — it points to the line
  // the session already has, or says by name why the thing can't be
  // counted here (no balance row in this warehouse, a serial not here).
  const findItem = async () => {
    clearMessages();
    setHighlight(null);
    try {
      const found = await api.post<{ line: string; message: string }>(`/stock-documents/${doc.id}/find-item/`, { q: findQuery });
      setNotice(found.message);
      setHighlight(found.line);
      document.getElementById(`count-line-${found.line}`)?.scrollIntoView({ block: "center" });
    } catch (err) {
      fail(err);
    }
  };

  const saveSurplusCosts = async () => {
    clearMessages();
    try {
      await api.post(`/stock-documents/${doc.id}/surplus-costs/`, {
        entries: surplusRows.map((row) => ({ line: Number(row.line), unit_cost: costs[row.line] ?? "" })),
      });
      setNotice(t("stockSurplusCostsSaved"));
      reload();
    } catch (err) {
      const body = (err as { body?: { errors?: ImportError[] } }).body;
      if (body?.errors) {
        setError(body.errors.map((e) => e.reason).join(" "));
        return;
      }
      fail(err);
    }
  };

  const importCsv = async (file: File) => {
    clearMessages();
    try {
      await api.post(`/stock-documents/${doc.id}/import-counts/`, { csv: await file.text() });
      setNotice(t("stockCountsSaved"));
      reload();
    } catch (err) {
      const body = (err as { body?: { errors?: ImportError[] } }).body;
      if (body?.errors) setImportErrors(body.errors);
      fail(err);
    }
  };

  const downloadTemplate = () => {
    const rows = [["sku", "batch", "counted_qty", "serials"]];
    for (const line of doc.lines) rows.push([line.item_sku, line.batch_number ?? "", "", ""]);
    const text = "﻿" + rows.map((r) => r.map(csvCell).join(",")).join("\n") + "\n";
    const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `count-${doc.warehouse_name}-${doc.date}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const runAction = async (action: string, body?: unknown) => {
    clearMessages();
    try {
      const result = await api.post<StockDocument>(`/stock-documents/${doc.id}/${action}/`, body ?? {});
      setDrift(null);
      if (action === "reverse") {
        router.push(`/dashboard/inventory/stock/${result.id}`);
        return;
      }
      reload();
    } catch (err) {
      const e = err as { status?: number; body?: { code?: string; drift?: CountDrift[] } };
      if (action === "post" && e.status === 409 && e.body?.code === "count_drift") {
        setDrift(e.body.drift ?? []);
        return;
      }
      fail(err);
    }
  };

  const remove = async () => {
    if (!window.confirm(t("stockDeleteConfirm"))) return;
    clearMessages();
    try {
      await api.delete(`/stock-documents/${doc.id}/`);
      router.push("/dashboard/inventory/stock/counts");
    } catch (err) {
      fail(err);
    }
  };

  const submitReason = async () => {
    if (!reasonMode) return;
    await runAction(reasonMode, { reason: reasonText });
    setReasonMode(null);
    setReasonText("");
  };

  const frozen = ["draft", "pending_approval", "approved"].includes(doc.status) && !doc.reverses;
  const surplusRows = (variances?.lines ?? []).filter((r) => r.variance_qty !== null && Number(r.variance_qty) > 0);
  const canEditCost = isDraft && canPost;

  return (
    <div>
      <button className="secondary" onClick={() => router.push("/dashboard/inventory/stock/counts")}>← {t("back")}</button>
      <h1 style={{ marginTop: "1rem" }}>{t("stockCountDoc")} {doc.number || `(${t("draft")})`}</h1>
      <p><StatusBadge status={doc.status} /></p>

      <div className="card">
        <p>{t("stockCountDate")}: {formatDate(doc.date, "form")}</p>
        <p>{t("legalEntity")}: {doc.legal_entity_name}</p>
        <p>{t("warehouse")}: {doc.warehouse_name}</p>
        <p>{t("stockCountScope")}: {doc.count_scope || t("stockCountWholeWarehouse")}</p>
        {doc.notes && <p>{t("notes")}: {doc.notes}</p>}
        {doc.reverses && (
          <p>{t("stockReversalOf")}: <Link href={`/dashboard/inventory/stock/${doc.reverses}`}>{doc.reverses}</Link></p>
        )}
        {doc.reversed_by_id && (
          <p>{t("stockReversedBy")}: <Link href={`/dashboard/inventory/stock/${doc.reversed_by_id}`}>{doc.reversed_by_id}</Link></p>
        )}
        {doc.journal_entries.length > 0 && (
          <p>
            {t("relatedJournalEntry")}:{" "}
            {doc.journal_entries.map((je, i) => (
              <span key={je.id}>
                {i > 0 && "، "}
                <Link href={`/dashboard/accounting/journal-entries/${je.id}`}>{je.number || je.id}</Link>
              </span>
            ))}
          </p>
        )}
        {frozen && <p style={{ color: "var(--warning)" }}>{t("stockCountFreezeNote")}</p>}
      </div>

      <WarningsBanner warnings={error ? [error] : []} variant="error" />
      {notice && <p role="status" style={{ color: "var(--success)" }}>{notice}</p>}
      {importErrors.length > 0 && (
        <div className="card" data-testid="count-import-errors">
          <h3>{t("stockImportErrors")}</h3>
          <table>
            <thead><tr><th>{t("stockImportRow")}</th><th>{t("reason")}</th></tr></thead>
            <tbody>
              {importErrors.map((e) => (
                <tr key={`${e.row}-${e.reason}`}><td>{e.row}</td><td>{e.reason}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {drift && (
        <div className="card" data-testid="count-drift">
          <h3>{t("stockDriftTitle")}</h3>
          <table>
            <thead>
              <tr>
                <th>{t("stockItem")}</th>
                <th>{t("stockExpectedQty")}</th>
                <th>{t("stockCurrentQty")}</th>
                <th>{t("stockDrift")}</th>
              </tr>
            </thead>
            <tbody>
              {drift.map((d) => (
                <tr key={d.line}>
                  <td>{d.item_name}{d.batch_number ? ` / ${d.batch_number}` : ""}</td>
                  <td><span className="money">{d.expected_qty}</span></td>
                  <td><span className="money">{d.current_qty}</span></td>
                  <td><span className="money">{d.drift}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ marginTop: "0.75rem" }}>
            <button className="primary" onClick={() => runAction("post", { acknowledge_drift: true })}>{t("stockDriftConfirm")}</button>
            <button className="secondary" style={{ marginInlineStart: "0.5rem" }} onClick={() => setDrift(null)}>{t("cancel")}</button>
          </div>
        </div>
      )}

      <div style={{ display: "flex", gap: "0.5rem", margin: "1rem 0" }}>
        <button className={tab === "count" ? "primary" : "secondary"} onClick={() => setTab("count")}>{t("stockCountTab")}</button>
        <button className={tab === "variances" ? "primary" : "secondary"} onClick={() => setTab("variances")}>{t("stockVariancesTab")}</button>
      </div>

      {tab === "count" && (
        <div className="card">
          {isDraft && canManage && (
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end", marginBottom: "1rem" }}>
              <FormField name="find_item" label={t("stockFindItem")} hint={t("stockFindItemHint")}>
                <input
                  value={findQuery}
                  onChange={(e) => setFindQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      findItem();
                    }
                  }}
                />
              </FormField>
              <button className="secondary" type="button" onClick={findItem} disabled={!findQuery.trim()}>
                {t("stockFindItemButton")}
              </button>
            </div>
          )}
          <table>
            <thead>
              <tr>
                <th>{t("stockItem")}</th>
                <th>{t("stockBatch")}</th>
                <th>{t("stockExpectedQty")}</th>
                <th>{t("stockCountedQty")}</th>
              </tr>
            </thead>
            <tbody>
              {doc.lines.map((line) => (
                <tr
                  key={line.id}
                  id={`count-line-${line.id}`}
                  style={highlight === line.id ? { outline: "2px solid var(--warning)" } : undefined}
                >
                  <td>{line.item_sku} — {line.item_name}</td>
                  <td>{line.batch_number || "—"}</td>
                  <td><span className="money">{line.expected_qty}</span></td>
                  <td>
                    {!isDraft || !canManage ? (
                      line.counted_qty === null ? t("stockNotCounted") : (
                        <span className="money">
                          {line.counted_qty}
                          {line.counted_serial_numbers.length > 0 && ` (${line.counted_serial_numbers.join("، ")})`}
                        </span>
                      )
                    ) : (
                      <>
                        <FormField name={`counts.${line.id}.counted_qty`} label={t("stockCountedQty")} style={{ width: "120px" }}>
                          <input inputMode="decimal" value={qty[line.id] ?? ""} placeholder={t("stockNotCounted")} onChange={(e) => setQty({ ...qty, [line.id]: e.target.value })} />
                        </FormField>
                        {line.item_tracking === "serial" && (
                          <FormField name={`counts.${line.id}.serials`} label={t("stockCountedSerials")} hint={t("stockCountedSerialsHint")}>
                            <textarea rows={3} value={serials[line.id] ?? ""} onChange={(e) => setSerials({ ...serials, [line.id]: e.target.value })} />
                          </FormField>
                        )}
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {isDraft && canManage && (
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end", marginTop: "1rem" }}>
              <button className="primary" onClick={saveCounts}>{t("stockSaveCounts")}</button>
              <FormField name="count_csv" label={t("stockImportCsv")} hint={t("stockImportCsvHint")}>
                <input
                  type="file"
                  accept=".csv,text/csv"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) importCsv(file);
                    e.target.value = "";
                  }}
                />
              </FormField>
              <button className="secondary" type="button" onClick={downloadTemplate}>{t("stockDownloadTemplate")}</button>
            </div>
          )}
        </div>
      )}

      {tab === "variances" && variances && (
        <div className="card" data-testid="count-variances">
          <table>
            <thead>
              <tr>
                <th>{t("stockItem")}</th>
                <th>{t("stockBatch")}</th>
                <th>{t("stockExpectedQty")}</th>
                {variances.lines.some((r) => r.current_qty !== null) && <th>{t("stockCurrentQty")}</th>}
                <th>{t("stockCountedQty")}</th>
                <th>{t("stockVarianceQty")}</th>
                <th>{t("stockAvgCost")}</th>
                <th>{t("stockSurplusUnitCost")}</th>
                <th>{t("stockVarianceValue")}</th>
              </tr>
            </thead>
            <tbody>
              {variances.lines.map((row) => (
                <tr key={row.line}>
                  <td>{row.item_sku} — {row.item_name}</td>
                  <td>{row.batch_number || "—"}</td>
                  <td><span className="money">{row.expected_qty}</span></td>
                  {row.current_qty !== null && (
                    <td>
                      <span className="money">{row.current_qty}</span>
                      {row.counted_qty !== null && row.drift && Number(row.drift) !== 0 && (
                        <span className="money" style={{ color: "var(--warning)" }} title={t("stockDrift")}> ({row.drift})</span>
                      )}
                    </td>
                  )}
                  <td><span className="money">{row.counted_qty ?? t("stockNotCounted")}</span></td>
                  <td><span className="money">{row.variance_qty ?? "—"}</span></td>
                  <td><Money amount={row.avg_cost} /></td>
                  <td>
                    {row.variance_qty === null || Number(row.variance_qty) <= 0 ? "—" : canEditCost ? (
                      <FormField name={`surplus.${row.line}.unit_cost`} label={t("stockSurplusUnitCost")} style={{ width: "130px" }}>
                        <input
                          inputMode="decimal"
                          value={costs[row.line] ?? ""}
                          placeholder={row.avg_cost}
                          onChange={(e) => setCosts({ ...costs, [row.line]: e.target.value })}
                        />
                      </FormField>
                    ) : row.surplus_unit_cost !== null ? (
                      <Money amount={row.surplus_unit_cost} />
                    ) : (
                      t("stockSurplusAtAverage")
                    )}
                    {row.needs_cost && (
                      <div role="alert" style={{ color: "var(--danger)" }}>{t("stockSurplusNeedsCost")}</div>
                    )}
                  </td>
                  <td>{row.variance_value === null ? "—" : <Money amount={row.variance_value} />}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p style={{ marginTop: "0.75rem" }}>
            {t("stockCountedLines")}: {variances.counted_lines} / {variances.total_lines}
            {" — "}{t("stockShortageValue")}: <Money amount={variances.shortage_value} />
            {" — "}{t("stockSurplusValue")}: <Money amount={variances.surplus_value} />
            {" — "}{t("stockNetVariance")}: <Money amount={variances.net_value} />
          </p>
          {doc.total_is_estimate && <p style={{ color: "var(--muted)" }}>{t("stockEstimate")}</p>}
          {canEditCost && surplusRows.length > 0 && (
            <div style={{ marginTop: "0.75rem" }}>
              <p style={{ color: "var(--muted)" }}>{t("stockSurplusUnitCostHint")}</p>
              <button className="primary" onClick={saveSurplusCosts}>{t("stockSaveSurplusCosts")}</button>
            </div>
          )}
        </div>
      )}

      {reasonMode ? (
        <div className="card">
          <h3>{reasonMode === "reject" ? t("rejectReason") : t("stockReverseReason")}</h3>
          <FormField name="reason" required style={{ maxWidth: "320px" }}>
            <input value={reasonText} onChange={(e) => setReasonText(e.target.value)} style={{ minWidth: "300px" }} />
          </FormField>
          <div style={{ marginTop: "0.75rem" }}>
            <button className="primary" onClick={submitReason}>{t("save")}</button>
            <button type="button" className="secondary" style={{ marginInlineStart: "0.5rem" }} onClick={() => { setReasonMode(null); setReasonText(""); }}>
              {t("cancel")}
            </button>
          </div>
        </div>
      ) : (
        <div className="card" style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "end" }}>
          {isDraft && canManage && (
            <>
              <button className="primary" onClick={() => runAction("submit")}>{t("submitForApproval")}</button>
              <button className="secondary" onClick={remove}>{t("stockDelete")}</button>
            </>
          )}
          {doc.status === "pending_approval" && (
            <>
              {canPost && <button className="primary" onClick={() => runAction("approve")}>{t("approve")}</button>}
              {canPost && <button className="secondary" onClick={() => setReasonMode("reject")}>{t("reject")}</button>}
              {canManage && doc.created_by === user?.id && (
                <button className="secondary" onClick={() => runAction("withdraw")}>{t("withdraw")}</button>
              )}
            </>
          )}
          {doc.status === "approved" && canPost && !drift && (
            <button className="primary" onClick={() => runAction("post")}>{t("post")}</button>
          )}
          {doc.status === "posted" && canPost && !doc.reverses && (
            <button className="secondary" onClick={() => setReasonMode("reverse")}>{t("reverse")}</button>
          )}
          <FormField name="blind_count" label={t("stockBlindCount")}>
            <input type="checkbox" checked={blind} onChange={(e) => setBlind(e.target.checked)} />
          </FormField>
          <Link href={`/print/stock/count/${doc.id}${blind ? "?blind=1" : ""}`} className="secondary" target="_blank">
            {t("stockPrintCountSheet")}
          </Link>
        </div>
      )}

      <ChangeHistoryTab
        targetType="stock_document"
        targetId={doc.id}
        describe={(entry) => describeChange(entry, t("stockSurplusAtAverage"))}
      />
    </div>
  );
}
