"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { api, generalError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import { AttachmentPanel } from "@/components/AttachmentPanel";
import { ChangeHistoryTab } from "@/components/ChangeHistoryTab";
import { FormField } from "@/components/FormField";
import { Money } from "@/components/Money";
import { StatusBadge } from "@/components/StatusBadge";
import { StockDocumentForm } from "@/components/StockDocumentForm";
import { STOCK_KIND_SLUG } from "@/components/StockDocumentScreen";
import { WarningsBanner } from "@/components/WarningsBanner";
import { formatDate } from "@/lib/date";
import type { StockDocument, StockDocumentKind } from "@/lib/types";

const DOC_LABEL: Record<StockDocumentKind, string> = {
  receipt: "stockReceiptDoc",
  issue: "stockIssueDoc",
  transfer: "stockTransferDoc",
};

/** Sprint 7.4: one detail screen for all three kinds — same layout as
 * the voucher detail screen. Buttons follow status and permission; the
 * API refuses every action that doesn't fit, whatever is shown. */
export default function StockDocumentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { t } = useLocale();
  const { hasPermission, user } = useAuth();
  const [doc, setDoc] = useState<StockDocument | null>(null);
  const [editing, setEditing] = useState(false);
  const [reasonMode, setReasonMode] = useState<"reject" | "reverse" | null>(null);
  const [reasonText, setReasonText] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    api.get<StockDocument>(`/stock-documents/${id}/`).then(setDoc).catch(() => setDoc(null));
  };
  useEffect(load, [id]);

  if (!doc) return null;

  const canManage = hasPermission("inventory.manage");
  const canPost = hasPermission("inventory.post");
  const fail = (err: unknown) =>
    setError(generalError((err as { body?: unknown }).body, t("couldNotSave"), (err as { status?: number }).status));

  const runAction = async (action: string, body?: unknown) => {
    setError(null);
    try {
      const result = await api.post<StockDocument>(`/stock-documents/${doc.id}/${action}/`, body ?? {});
      if (action === "reverse") {
        router.push(`/dashboard/inventory/stock/${result.id}`);
        return;
      }
      load();
    } catch (err) {
      fail(err);
    }
  };

  const remove = async () => {
    if (!window.confirm(t("stockDeleteConfirm"))) return;
    setError(null);
    try {
      await api.delete(`/stock-documents/${doc.id}/`);
      router.push(`/dashboard/inventory/stock/${STOCK_KIND_SLUG[doc.kind]}`);
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

  const isTransfer = doc.kind === "transfer";

  return (
    <div>
      <button className="secondary" onClick={() => router.push(`/dashboard/inventory/stock/${STOCK_KIND_SLUG[doc.kind]}`)}>
        ← {t("back")}
      </button>

      <h1 style={{ marginTop: "1rem" }}>
        {t(DOC_LABEL[doc.kind])} {doc.number || `(${t("draft")})`}
      </h1>
      <p>
        <StatusBadge status={doc.status} />
        {isTransfer && doc.status === "posted" && !doc.reverses && (
          <span style={{ marginInlineStart: "0.5rem", color: "var(--muted)" }}>
            {doc.transfer_received ? t("stockReceived") : t("stockInTransit")}
          </span>
        )}
      </p>

      {editing ? (
        <div className="card">
          <StockDocumentForm
            kind={doc.kind}
            document={doc}
            onSaved={(saved) => { setDoc(saved); setEditing(false); }}
            onCancel={() => setEditing(false)}
          />
        </div>
      ) : (
        <>
          <div className="card">
            <p>{t("stockDocDate")}: {formatDate(doc.date, "form")}</p>
            <p>{t("legalEntity")}: {doc.legal_entity_name}</p>
            <p>{isTransfer ? t("stockFromWarehouse") : t("warehouse")}: {doc.warehouse_name}</p>
            {isTransfer && <p>{t("stockToWarehouse")}: {doc.to_warehouse_name} ({doc.to_legal_entity_name})</p>}
            <p>{t("stockParty")}: {doc.party_name || "—"}</p>
            {!isTransfer && <p>{t("account")}: {doc.account_name || "—"}</p>}
            <p>{t("reference")}: {doc.reference || "—"}</p>
            <p>{t("notes")}: {doc.notes || "—"}</p>
            {doc.reverses && (
              <p>{t("stockReversalOf")}: <Link href={`/dashboard/inventory/stock/${doc.reverses}`}>{doc.reverses}</Link></p>
            )}
            {doc.reversed_by_id && (
              <p>{t("stockReversedBy")}: <Link href={`/dashboard/inventory/stock/${doc.reversed_by_id}`}>{doc.reversed_by_id}</Link></p>
            )}
            <p>
              {t("relatedJournalEntry")}:{" "}
              {doc.journal_entries.length === 0
                ? "—"
                : doc.journal_entries.map((je, i) => (
                    <span key={je.id}>
                      {i > 0 && "، "}
                      <Link href={`/dashboard/accounting/journal-entries/${je.id}`}>{je.number || je.id}</Link>
                    </span>
                  ))}
            </p>
          </div>

          <div className="card">
            <table>
              <thead>
                <tr>
                  <th>{t("stockItem")}</th>
                  <th>{t("stockUnit")}</th>
                  <th>{t("quantity")}</th>
                  <th>{t("stockUnitCost")}</th>
                  <th>{t("stockBatch")}</th>
                  <th>{t("stockSerials")}</th>
                  <th>{t("costCenter")}</th>
                </tr>
              </thead>
              <tbody>
                {doc.lines.map((line) => (
                  <tr key={line.id}>
                    <td>{line.item_sku} — {line.item_name}</td>
                    <td>{line.uom_name || t("stockBaseUnit")}</td>
                    <td className="money">{line.qty}</td>
                    <td>{doc.kind === "receipt" || doc.status === "posted" || doc.status === "reversed" ? <Money amount={line.unit_cost} /> : "—"}</td>
                    <td>{line.batch_number ? `${line.batch_number}${line.batch_expiry ? ` (${formatDate(line.batch_expiry, "form")})` : ""}` : "—"}</td>
                    <td>{line.serial_numbers.length ? line.serial_numbers.join("، ") : "—"}</td>
                    <td>{line.cost_center_name || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p style={{ marginTop: "0.75rem" }}>
              {t("stockTotalQty")}: <span className="money">{doc.total_qty}</span>
              {" — "}
              {t("stockTotalValue")}: <Money amount={doc.total_value} />
            </p>
            {doc.total_is_estimate && <p style={{ color: "var(--muted)" }}>{t("stockEstimate")}</p>}
          </div>
        </>
      )}

      <WarningsBanner warnings={error ? [error] : []} variant="error" />

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
        !editing && (
          <div className="card" style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            {doc.status === "draft" && canManage && (
              <>
                <button className="primary" onClick={() => runAction("submit")}>{t("submitForApproval")}</button>
                <button className="secondary" onClick={() => setEditing(true)}>{t("edit")}</button>
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
            {doc.status === "approved" && canPost && (
              <button className="primary" onClick={() => runAction("post")}>{t("post")}</button>
            )}
            {doc.status === "posted" && canPost && !doc.reverses && !(isTransfer && doc.transfer_received) && (
              <button className="secondary" onClick={() => setReasonMode("reverse")}>{t("reverse")}</button>
            )}
            {isTransfer && doc.status === "posted" && !doc.reverses && !doc.transfer_received && canPost && (
              <button className="primary" onClick={() => runAction("confirm-receipt")}>{t("stockConfirmReceipt")}</button>
            )}
            {(doc.status === "posted" || doc.status === "reversed") && (
              <Link href={`/print/stock/${doc.kind}/${doc.id}`} className="secondary" target="_blank">{t("printButton")}</Link>
            )}
          </div>
        )
      )}

      <AttachmentPanel targetType="stock_document" targetId={doc.id} />
      <ChangeHistoryTab targetType="stock_document" targetId={doc.id} />
    </div>
  );
}
