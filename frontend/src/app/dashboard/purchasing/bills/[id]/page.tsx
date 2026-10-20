"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { api, generalError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import { AttachmentPanel } from "@/components/AttachmentPanel";
import { ChangeHistoryTab } from "@/components/ChangeHistoryTab";
import { promptDialog } from "@/components/Dialog";
import { FormField } from "@/components/FormField";
import { Money } from "@/components/Money";
import { StatusBadge } from "@/components/StatusBadge";
import { SupplierBillForm } from "@/components/SupplierBillForm";
import { WarningsBanner } from "@/components/WarningsBanner";
import { formatDate } from "@/lib/date";
import type { SupplierBill } from "@/lib/types";

// apps.approvals.services.approve()'s own text when only an Owner's
// emergency override can approve — same handling as the asset screen.
const EMERGENCY_APPROVAL_REQUIRED = "الاعتماد الاضطراري يشترط سببًا إلزاميًا";

const LINE_TYPE_LABEL: Record<string, string> = {
  service: "billLineService",
  expense: "billLineExpense",
  asset: "billLineAsset",
};

/** Sprint 8.1 (D12): one supplier bill — header, lines, the server's
 * totals, approve/post/reverse by status and permission, the original
 * invoice (AttachmentPanel, with the mandatory-attachment rule enforced at
 * submit) and the change history. No «دفع نقدي الآن» here: pay-now ships
 * in 8.2 with the generalized allocation, so «المستحق» is the total. */
export default function SupplierBillDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { t } = useLocale();
  const { hasPermission, user } = useAuth();
  const [bill, setBill] = useState<SupplierBill | null>(null);
  const [editing, setEditing] = useState(false);
  const [reasonMode, setReasonMode] = useState<"reject" | "reverse" | null>(null);
  const [reasonText, setReasonText] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    api.get<SupplierBill>(`/purchasing/bills/${id}/`).then(setBill);
  };
  useEffect(load, [id]);

  if (!bill) return null;

  const canManage = hasPermission("purchasing.manage");
  const canPost = hasPermission("purchasing.post");
  const fail = (err: unknown) =>
    setError(generalError((err as { body?: unknown }).body, t("couldNotSave"), (err as { status?: number }).status));

  const runAction = async (action: string, body?: Record<string, unknown>) => {
    setError(null);
    try {
      await api.post(`/purchasing/bills/${bill.id}/${action}/`, body ?? {});
      load();
    } catch (err) {
      if (action === "approve" && generalError((err as { body?: unknown }).body, "").includes(EMERGENCY_APPROVAL_REQUIRED)) {
        const reason = await promptDialog({ title: t("emergencyApprovalReason"), message: t("emergencyApprovalReasonHint") });
        if (reason) await runAction("approve", { emergency_reason: reason });
        return;
      }
      fail(err);
    }
  };

  const remove = async () => {
    if (!window.confirm(t("billDeleteConfirm"))) return;
    setError(null);
    try {
      await api.delete(`/purchasing/bills/${bill.id}/`);
      router.push("/dashboard/purchasing/bills");
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

  return (
    <div>
      <button className="secondary" onClick={() => router.push("/dashboard/purchasing/bills")}>← {t("back")}</button>

      <h1 style={{ marginTop: "1rem" }}>
        {t("supplierBillDocType")} {bill.number || `(${t("draft")})`}
      </h1>
      <p><StatusBadge status={bill.status} /></p>

      {editing ? (
        <div className="card">
          <SupplierBillForm bill={bill} onSaved={(saved) => { setBill(saved); setEditing(false); }} onCancel={() => setEditing(false)} />
        </div>
      ) : (
        <>
          <div className="card" data-testid="bill-header">
            <p>{t("billSupplier")}: {bill.supplier_name}</p>
            <p>{t("supplierInvoiceNumber")}: {bill.bill_number}</p>
            <p>{t("legalEntity")}: {bill.legal_entity_name}</p>
            <p>{t("billDate")}: {formatDate(bill.date, "form")}</p>
            <p>{t("dueDate")}: {bill.due_date ? formatDate(bill.due_date, "form") : "—"}</p>
            <p>{t("currency")}: {bill.currency}{bill.currency && bill.exchange_rate !== "1.00000000" ? ` — ${t("billExchangeRate")} ${bill.exchange_rate}` : ""}</p>
            <p>{t("reference")}: {bill.reference || "—"}</p>
            <p>{t("notes")}: {bill.notes || "—"}</p>
            <p>
              {t("relatedJournalEntry")}:{" "}
              {bill.journal_entry ? (
                <Link href={`/dashboard/accounting/journal-entries/${bill.journal_entry}`}>{bill.journal_entry_number}</Link>
              ) : "—"}
            </p>
          </div>

          <div className="card">
            <table data-testid="bill-lines">
              <thead>
                <tr>
                  <th>{t("billLineType")}</th>
                  <th>{t("description")}</th>
                  <th>{t("account")}</th>
                  <th>{t("costCenter")}</th>
                  <th>{t("quantity")}</th>
                  <th>{t("unitPrice")}</th>
                  <th>{t("billLineNet")}</th>
                  <th>{t("taxCode")}</th>
                  <th>{t("billLineVat")}</th>
                  <th>{t("billWithholding")}</th>
                  <th>{t("billAssetCreated")}</th>
                </tr>
              </thead>
              <tbody>
                {bill.lines.map((line) => (
                  <tr key={line.id}>
                    <td>{t(LINE_TYPE_LABEL[line.line_type])}</td>
                    <td>{line.line_type === "asset" ? `${line.asset_name} (${t(line.asset_category || "other")})` : line.description || "—"}</td>
                    <td>{line.line_type === "asset" ? t("billLineAsset") : `${line.account_code} — ${line.account_name}`}</td>
                    <td>{line.cost_center_name || "—"}</td>
                    <td><span className="money">{line.qty}</span></td>
                    <td><Money amount={line.unit_price} /></td>
                    <td><Money amount={line.net} /></td>
                    <td>
                      {line.tax_code_display} ({line.tax_rate}%)
                      {line.is_reverse_charge && ` — ${t("billReverseCharge")}`}
                      {!line.vat_deductible && ` — ${t("billCapitalizedVat")}`}
                    </td>
                    <td><Money amount={line.tax_amount} /></td>
                    <td>{line.wht_code_display ? <>{line.wht_code_display}: <Money amount={line.wht_amount} /></> : "—"}</td>
                    <td>{line.asset ? <Link href={`/dashboard/assets/${line.asset}`}>{line.asset_code}</Link> : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="card" data-testid="bill-totals">
            <p>{t("billSubtotal")}: <Money amount={bill.subtotal} currency={bill.currency} /></p>
            <p>{t("billDeductibleVat")}: <Money amount={bill.deductible_tax} currency={bill.currency} /></p>
            <p>{t("billCapitalizedVat")}: <Money amount={bill.capitalized_tax} currency={bill.currency} /></p>
            <p>{t("billReverseChargeVat")}: <Money amount={bill.reverse_charge_tax} currency={bill.currency} /></p>
            <p>{t("billExpectedWithholding")}: <Money amount={bill.wht_expected} currency={bill.currency} /></p>
            <p><strong>{t("billTotal")}: <Money amount={bill.total} currency={bill.currency} /></strong></p>
            <p><strong>{t("billAmountDue")}: <Money amount={bill.total} currency={bill.currency} /></strong></p>
          </div>
        </>
      )}

      <WarningsBanner warnings={error ? [error] : []} variant="error" />

      {reasonMode ? (
        <div className="card">
          <h3>{reasonMode === "reject" ? t("rejectReason") : t("billReverseReason")}</h3>
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
            {bill.status === "draft" && canManage && (
              <>
                <button className="primary" onClick={() => runAction("submit")}>{t("submitForApproval")}</button>
                <button className="secondary" onClick={() => setEditing(true)}>{t("edit")}</button>
                <button className="secondary" onClick={remove}>{t("stockDelete")}</button>
              </>
            )}
            {bill.status === "pending_approval" && (
              <>
                {canPost && <button className="primary" onClick={() => runAction("approve")}>{t("approve")}</button>}
                {canPost && <button className="secondary" onClick={() => setReasonMode("reject")}>{t("reject")}</button>}
                {canManage && bill.created_by_id === user?.id && (
                  <button className="secondary" onClick={() => runAction("withdraw")}>{t("withdraw")}</button>
                )}
              </>
            )}
            {bill.status === "approved" && canPost && (
              <button className="primary" onClick={() => runAction("post")}>{t("post")}</button>
            )}
            {bill.status === "posted" && canPost && (
              <button className="secondary" onClick={() => setReasonMode("reverse")}>{t("reverse")}</button>
            )}
            {(bill.status === "posted" || bill.status === "reversed") && (
              <Link href={`/print/supplier-bills/${bill.id}`} className="secondary" target="_blank">{t("printButton")}</Link>
            )}
          </div>
        )
      )}

      <AttachmentPanel targetType="supplier_bill" targetId={bill.id} />
      <ChangeHistoryTab targetType="supplier_bill" targetId={bill.id} />
    </div>
  );
}
