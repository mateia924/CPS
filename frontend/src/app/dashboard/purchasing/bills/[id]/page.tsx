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
import { ErrorState, apiErrorKind, type ApiErrorKind } from "@/components/ScreenErrors";
import type { Bank, CashBox, OpenAdvance, Paginated, SupplierBill } from "@/lib/types";

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
 * submit) and the change history.
 * Sprint 8.2 (D7): what has been paid against it and what is left
 * («المستحق»), «سداد» (the payment-voucher screen, pre-filled), «دفع نقدي
 * الآن» (a payment voucher for the whole balance, posted at once), and the
 * supplier's open advances to apply. */
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
  const [advances, setAdvances] = useState<OpenAdvance[]>([]);
  const [advancesError, setAdvancesError] = useState<ApiErrorKind | null>(null);
  const [applyAmounts, setApplyAmounts] = useState<Record<string, string>>({});
  const [treasuries, setTreasuries] = useState<{ kind: string; id: string; label: string; currency: string; legal_entity: string }[]>([]);
  const [treasuriesError, setTreasuriesError] = useState<ApiErrorKind | null>(null);
  const [payFrom, setPayFrom] = useState("");
  const [payMethod, setPayMethod] = useState("bank_transfer");
  const [paidVoucher, setPaidVoucher] = useState<{ id: string; number: string; status: string } | null>(null);

  const load = () => {
    api.get<SupplierBill>(`/purchasing/bills/${id}/`).then((data) => {
      setBill(data);
      if (data.status === "posted") {
        api
          .get<OpenAdvance[]>(`/purchasing/bills/${id}/open-advances/`)
          .then((rows) => { setAdvances(rows); setAdvancesError(null); })
          .catch((err) => setAdvancesError(apiErrorKind(err) ?? "server-error"));
      }
    });
  };
  useEffect(load, [id]);

  const canPayNow = hasPermission("purchasing.post") && hasPermission("vouchers.post");
  useEffect(() => {
    if (!bill || bill.status !== "posted" || !canPayNow) return;
    Promise.all([api.get<Paginated<Bank>>("/banks/"), api.get<Paginated<CashBox>>("/cash-boxes/")])
      .then(([banks, boxes]) => {
        setTreasuries([
          ...banks.results.map((b) => ({ kind: "bank", id: b.id, label: `${t("bank")}: ${b.name}`, currency: b.currency, legal_entity: b.legal_entity })),
          ...boxes.results.map((c) => ({ kind: "cash_box", id: c.id, label: `${t("cashBox")}: ${c.name}`, currency: c.currency, legal_entity: c.legal_entity })),
        ]);
        setTreasuriesError(null);
      })
      .catch((err) => setTreasuriesError(apiErrorKind(err) ?? "server-error"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bill?.id, bill?.status, canPayNow]);

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

  const payNow = async () => {
    setError(null);
    const [kind, treasuryId] = payFrom.split(":");
    try {
      const result = await api.post<{ voucher_id: string; voucher_number: string; voucher_status: string }>(
        `/purchasing/bills/${bill.id}/pay-now/`, { treasury_kind: kind, treasury_id: treasuryId, payment_method: payMethod },
      );
      setPaidVoucher({ id: result.voucher_id, number: result.voucher_number, status: result.voucher_status });
      load();
    } catch (err) {
      fail(err);
    }
  };

  const applyAdvance = async (advance: OpenAdvance) => {
    setError(null);
    try {
      await api.post(`/purchasing/bills/${bill.id}/apply-advance/`, {
        source_line: advance.line_id, amount: applyAmounts[advance.line_id] || advance.remaining_fc,
      });
      load();
    } catch (err) {
      fail(err);
    }
  };

  const withdrawAdvance = async (applicationId: string) => {
    const reason = await promptDialog({ title: t("withdrawAdvance"), message: t("billReverseReason") });
    if (!reason) return;
    setError(null);
    try {
      await api.post(`/purchasing/bills/${bill.id}/withdraw-advance/`, { application: applicationId, reason });
      load();
    } catch (err) {
      fail(err);
    }
  };

  const payableTreasuries = treasuries.filter((x) => x.currency === bill.currency && x.legal_entity === bill.legal_entity);
  const isOpen = bill.status === "posted" && Number(bill.balance_fc) > 0;

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
            {bill.status === "posted" && <p>{t("billPaid")}: <Money amount={bill.paid_fc} currency={bill.currency} /></p>}
            <p><strong>{t("billAmountDue")}: <Money amount={bill.status === "posted" ? bill.balance_fc : bill.total} currency={bill.currency} /></strong></p>
          </div>

          {(bill.payments.length > 0 || bill.advance_applications.length > 0) && (
            <div className="card" data-testid="bill-payments">
              <h3 style={{ marginTop: 0 }}>{t("billPayments")}</h3>
              <table>
                <thead>
                  <tr>
                    <th>{t("date")}</th>
                    <th>{t("number")}</th>
                    <th>{t("billLineType")}</th>
                    <th>{t("amount")}</th>
                    <th>{t("fxDifference")}</th>
                    <th>{t("status")}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {bill.payments.map((p) => (
                    <tr key={p.id}>
                      <td>{formatDate(p.date, "form")}</td>
                      <td><Link href={`/dashboard/treasury/vouchers/${p.voucher_id}`}>{p.voucher_number}</Link></td>
                      <td>{t("paymentVouchers")}</td>
                      <td><Money amount={p.amount_fc} currency={bill.currency} /></td>
                      <td><Money amount={p.fx_difference_base} /></td>
                      <td>{p.is_reversed ? t("reversed") : t("posted")}</td>
                      <td />
                    </tr>
                  ))}
                  {bill.advance_applications.map((a) => (
                    <tr key={a.id}>
                      <td>{formatDate(a.date, "form")}</td>
                      <td><Link href={`/dashboard/treasury/vouchers/${a.voucher_id}`}>{a.voucher_number}</Link></td>
                      <td>{t(a.kind === "advance" ? "advanceLineType" : "onAccountLineType")}</td>
                      <td><Money amount={a.amount_fc} currency={bill.currency} /></td>
                      <td><Money amount={a.fx_difference_base} /></td>
                      <td>{a.is_reversed ? t("reversed") : t("posted")}</td>
                      <td>
                        {!a.is_reversed && hasPermission("purchasing.post") && (
                          <button className="secondary" onClick={() => withdrawAdvance(a.id)}>{t("withdrawAdvance")}</button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {isOpen && (
            <div className="card" data-testid="bill-settle">
              <h3 style={{ marginTop: 0 }}>{t("billSettle")}</h3>
              {hasPermission("vouchers.add") && (
                <p>
                  <Link
                    className="secondary"
                    href={`/dashboard/treasury/vouchers/payment?party=${bill.supplier}&party_role=supplier&bill=${bill.id}&amount_fc=${bill.balance_fc}`} // money-ok: a URL parameter, not a displayed amount
                  >
                    {t("billPayButton")}
                  </Link>
                </p>
              )}
              {canPayNow && (treasuriesError ? (
                <ErrorState kind={treasuriesError} compact />
              ) : (
                <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "flex-end" }}>
                  <FormField name="pay_from" label={`${t("payNowTitle")} — ${t("payNowFrom")}`} style={{ minWidth: "240px" }}>
                    <select value={payFrom} onChange={(e) => setPayFrom(e.target.value)}>
                      <option value="">—</option>
                      {payableTreasuries.map((x) => (
                        <option key={x.id} value={`${x.kind}:${x.id}`}>{x.label} ({x.currency})</option>
                      ))}
                    </select>
                  </FormField>
                  <FormField name="pay_method" label={t("paymentMethod")}>
                    <select value={payMethod} onChange={(e) => setPayMethod(e.target.value)}>
                      <option value="cash">{t("paymentMethodCash")}</option>
                      <option value="bank_transfer">{t("paymentMethodBankTransfer")}</option>
                      <option value="cheque">{t("paymentMethodCheque")}</option>
                      <option value="card">{t("paymentMethodCard")}</option>
                      <option value="other">{t("paymentMethodOther")}</option>
                    </select>
                  </FormField>
                  <button className="primary" disabled={!payFrom} onClick={payNow}>{t("payNowButton")}</button>
                </div>
              ))}
              {paidVoucher && (
                <p data-testid="pay-now-result">
                  {t("payNowDone")}: <Link href={`/dashboard/treasury/vouchers/${paidVoucher.id}`}>{paidVoucher.number || paidVoucher.id}</Link> — {t(paidVoucher.status)}
                </p>
              )}

              <h4>{t("billAdvancesTitle")}</h4>
              {advancesError ? (
                <ErrorState kind={advancesError} compact />
              ) : advances.length === 0 ? (
                <p style={{ color: "var(--muted)" }}>{t("noOpenAdvances")}</p>
              ) : (
                <table data-testid="open-advances">
                  <tbody>
                    {advances.map((a) => (
                      <tr key={a.line_id}>
                        <td><Link href={`/dashboard/treasury/vouchers/${a.voucher_id}`}>{a.voucher_number}</Link></td>
                        <td>{t(a.kind === "advance" ? "advanceLineType" : "onAccountLineType")}</td>
                        <td>{t("remaining")}: <Money amount={a.remaining_fc} currency={a.currency} /></td>
                        <td>
                          <FormField name={`apply_${a.line_id}`} label={t("amount")}>
                            <input
                              type="number" step="0.01" min="0.01" placeholder={a.remaining_fc} value={applyAmounts[a.line_id] ?? ""}
                              onChange={(e) => setApplyAmounts((prev) => ({ ...prev, [a.line_id]: e.target.value }))}
                            />
                          </FormField>
                        </td>
                        <td>
                          {hasPermission("purchasing.post") && (
                            <button className="secondary" onClick={() => applyAdvance(a)}>{t("applyAdvance")}</button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
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
