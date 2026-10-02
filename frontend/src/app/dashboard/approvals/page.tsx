"use client";

import { Fragment, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, generalError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { FormField } from "@/components/FormField";
import { Money } from "@/components/Money";
import { WarningsBanner } from "@/components/WarningsBanner";
import { useLocale } from "@/lib/i18n";
import { formatDateTime } from "@/lib/date";
import type { EmergencyApproval, PendingApproval, PendingApprovalsResponse } from "@/lib/types";

// Sprint 6.3 (decision 8): opening_balance's approve requires a written
// attestation (>= 20 chars) the generic one-click flow below has no
// field for — those rows route to their own detail screen (which has
// the attestation textarea) instead of a blind POST.
const REQUIRES_DETAIL_SCREEN = new Set<PendingApproval["doc_type"]>(["opening_balance"]);

const DOC_TYPE_LABEL: Record<PendingApproval["doc_type"], string> = {
  journal_entry: "journalEntryDocType",
  invoice: "invoiceDocType",
  voucher_receipt: "voucherReceiptDocType",
  voucher_payment: "voucherPaymentDocType",
  voucher_settlement: "voucherSettlementDocType",
  iban_change: "ibanChangeDocType",
  opening_balance: "openingBalanceDocType",
  asset_depreciation: "assetDepreciationDocType",
  asset_addition: "assetAdditionDocType",
  asset_disposal: "assetDisposalDocType",
};

// Sprint 6.3: fixes a pre-existing gap (sprint 5.5) — an "iban_change"
// row's approve button called POST /undefined/{id}/approve/ since this
// map never had an entry for it; opening_balance joins it now.
const DOC_TYPE_PATH: Record<PendingApproval["doc_type"], string> = {
  journal_entry: "journal-entries",
  invoice: "invoices",
  voucher_receipt: "vouchers",
  voucher_payment: "vouchers",
  voucher_settlement: "vouchers",
  iban_change: "iban-requests",
  opening_balance: "opening-balances",
  asset_depreciation: "depreciation-schedules",
  asset_addition: "depreciation-schedules",
  asset_disposal: "asset-disposals",
};

// Sprint 6.9.1 (item C): the emergency tab can show doc_types the
// generic inbox above doesn't render at all yet (e.g. recurring_entry)
// — a loose Record, not PendingApproval's exhaustive one, with a
// fallback to the raw string so an unrecognized type never crashes
// the screen instead of just showing an unlabeled row.
const EMERGENCY_DOC_TYPE_LABEL: Record<string, string> = {
  journal_entry: "journalEntryDocType",
  invoice: "invoiceDocType",
  voucher_receipt: "voucherReceiptDocType",
  voucher_payment: "voucherPaymentDocType",
  voucher_settlement: "voucherSettlementDocType",
  iban_change: "ibanChangeDocType",
  opening_balance: "openingBalanceDocType",
  recurring_entry: "recurringEntryDocType",
  asset_depreciation: "assetDepreciationDocType",
};

const EMERGENCY_DOC_TYPE_PATH: Record<string, string> = {
  journal_entry: "accounting/journal-entries",
  invoice: "invoices",
  voucher_receipt: "treasury/vouchers",
  voucher_payment: "treasury/vouchers",
  voucher_settlement: "treasury/vouchers",
  opening_balance: "accounting/opening-balances",
  recurring_entry: "accounting/recurring-entries",
};

export default function ApprovalInboxPage() {
  const { t } = useLocale();
  const router = useRouter();
  const { me } = useAuth();
  const [tab, setTab] = useState<"inbox" | "emergency">("inbox");
  const [rows, setRows] = useState<PendingApproval[]>([]);
  const [blocked, setBlocked] = useState<{ count: number; role_names: string[] }>({ count: 0, role_names: [] });
  const [emergencyRows, setEmergencyRows] = useState<EmergencyApproval[] | null>(null);
  // Sprint 6.5.15 (UAT item 7): "رفض بسبب" inline in the row, matching
  // the spec's own inbox mock — no separate screen needed for the
  // common case (opening_balance still routes to its own detail
  // screen, same as approve — its own attestation flow needs a real
  // form, not a one-line reason).
  const [rejectingId, setRejectingId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [rejectError, setRejectError] = useState<string | null>(null);

  const showEmergencyTab = !!me && me.roles.includes("Owner");

  const load = async () => {
    const data = await api.get<PendingApprovalsResponse>("/approvals/pending/");
    setRows(data.results);
    setBlocked(data.blocked);
  };

  const loadEmergency = async () => {
    const data = await api.get<EmergencyApproval[]>("/approvals/emergency/");
    setEmergencyRows(data);
  };

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    if (tab === "emergency" && emergencyRows === null) loadEmergency();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  const approve = async (row: PendingApproval) => {
    if (REQUIRES_DETAIL_SCREEN.has(row.doc_type)) {
      router.push(`/dashboard/accounting/${DOC_TYPE_PATH[row.doc_type]}/${row.id}`);
      return;
    }
    await api.post(`/${DOC_TYPE_PATH[row.doc_type]}/${row.id}/approve/`);
    load();
  };

  const confirmReject = async (row: PendingApproval) => {
    setRejectError(null);
    try {
      await api.post(`/${DOC_TYPE_PATH[row.doc_type]}/${row.id}/reject/`, { reason: rejectReason });
      setRejectingId(null);
      setRejectReason("");
      load();
    } catch (err) {
      setRejectError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  return (
    <div>
      <h1>{t("approvalInbox")}</h1>

      {showEmergencyTab && (
        <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
          <button className={tab === "inbox" ? "primary" : "secondary"} onClick={() => setTab("inbox")}>
            {t("approvalInbox")}
          </button>
          <button className={tab === "emergency" ? "primary" : "secondary"} onClick={() => setTab("emergency")}>
            {t("emergencyApprovalsNav")}
          </button>
        </div>
      )}

      {tab === "inbox" &&
        (rows.length === 0 ? (
          <p style={{ color: "var(--muted)" }}>
            {blocked.count > 0
              ? `${t("pendingApprovalsBlockedByHigherRole")}: ${blocked.count} (${blocked.role_names.join("، ")})`
              : t("noPendingApprovals")}
          </p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>{t("docType")}</th>
                <th>{t("number")}</th>
                <th>{t("date")}</th>
                <th>{t("details")}</th>
                <th>{t("amountBase")}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <Fragment key={`${row.doc_type}-${row.id}`}> {/* arabic-ok: React key, not displayed */}
                  <tr>
                    <td>{t(DOC_TYPE_LABEL[row.doc_type])}</td>
                    <td>
                      {row.number && EMERGENCY_DOC_TYPE_PATH[row.doc_type] ? (
                        <Link href={`/dashboard/${EMERGENCY_DOC_TYPE_PATH[row.doc_type]}/${row.id}`}>{row.number}</Link>
                      ) : (
                        row.number // links-ok: no own detail page to link to for this doc_type (iban_change/opening_balance/asset_disposal — see REQUIRES_DETAIL_SCREEN for the one that has one)
                      )}
                    </td>
                    <td>{row.date}</td>
                    <td>{row.description}</td>
                    <td><Money amount={row.amount_base} /></td>
                    <td style={{ display: "flex", gap: "0.5rem" }}>
                      {(row.can_approve || REQUIRES_DETAIL_SCREEN.has(row.doc_type)) && (
                        <button className="secondary" onClick={() => approve(row)}>
                          {REQUIRES_DETAIL_SCREEN.has(row.doc_type) ? t("viewDetails") : t("approve")}
                        </button>
                      )}
                      {!row.can_approve && !REQUIRES_DETAIL_SCREEN.has(row.doc_type) && (
                        <span style={{ color: "var(--muted)", fontSize: "0.85rem" }}>{t("cannotApproveOwnDocument")}</span>
                      )}
                      {!REQUIRES_DETAIL_SCREEN.has(row.doc_type) && (
                        <button
                          className="secondary"
                          onClick={() => {
                            setRejectingId(rejectingId === row.id ? null : row.id);
                            setRejectReason("");
                            setRejectError(null);
                          }}
                        >
                          {t("rejectWithReason")}
                        </button>
                      )}
                    </td>
                  </tr>
                  {rejectingId === row.id && (
                    <tr>
                      <td colSpan={6}>
                        <div style={{ display: "flex", gap: "0.5rem", alignItems: "start" }}>
                          <FormField name="reason" label={t("reason")} required style={{ minWidth: "260px" }}>
                            <input value={rejectReason} onChange={(e) => setRejectReason(e.target.value)} />
                          </FormField>
                          <button
                            className="secondary" style={{ marginTop: "1.6rem" }}
                            onClick={() => confirmReject(row)}
                          >
                            {t("save")}
                          </button>
                        </div>
                        <WarningsBanner warnings={rejectError ? [rejectError] : []} variant="error" />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        ))}

      {tab === "emergency" &&
        (!emergencyRows || emergencyRows.length === 0 ? (
          <p style={{ color: "var(--muted)" }}>{t("noEmergencyApprovals")}</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>{t("document")}</th>
                <th>{t("docType")}</th>
                <th>{t("amountBase")}</th>
                <th>{t("approvedBy")}</th>
                <th>{t("emergencyApprovalReason")}</th>
                <th>{t("date")}</th>
              </tr>
            </thead>
            <tbody>
              {emergencyRows.map((row) => {
                const path = EMERGENCY_DOC_TYPE_PATH[row.doc_type];
                const label = t(EMERGENCY_DOC_TYPE_LABEL[row.doc_type] || "") || row.doc_type;
                return (
                  <tr key={row.id}>
                    <td>
                      {path && row.target_id ? (
                        <Link href={`/dashboard/${path}/${row.target_id}`}>
                          {row.number || row.description || row.target_id}
                        </Link>
                      ) : (
                        row.number || row.description || "—"
                      )}
                    </td>
                    <td>{label}</td>
                    <td>{row.amount_base !== null ? <Money amount={row.amount_base} /> : "—"}</td>
                    <td>{row.approved_by_name || "—"}</td>
                    <td>{row.emergency_reason}</td>
                    <td>{formatDateTime(row.created_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ))}
    </div>
  );
}
