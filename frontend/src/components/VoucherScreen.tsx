"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api, fieldErrors, generalError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { StatusBadge } from "@/components/StatusBadge";
import { flattenLeafAccounts, type FlatAccountOption } from "@/lib/accounts";
import type {
  AccountTreeNode, Bank, CashBox, CostCenter, Custody, Invoice, LegalEntity,
  Paginated, Party, PartyRoleType, TaxCode, TreasuryKind, Voucher, VoucherLineType,
  VoucherPaymentMethod,
} from "@/lib/types";

interface LineDraft {
  lineType: VoucherLineType;
  invoice: string;
  account: string;
  taxCode: string;
  amountIncludesTax: boolean;
  costCenter: string;
  amountFc: string;
  description: string;
}

const EMPTY_LINE: LineDraft = {
  lineType: "on_account", invoice: "", account: "", taxCode: "",
  amountIncludesTax: false, costCenter: "", amountFc: "", description: "",
};

const ROLE_OPTIONS: PartyRoleType[] = ["customer", "supplier", "employee", "affiliate"];
const ROLE_LABEL_KEY: Record<PartyRoleType, string> = {
  customer: "customerRole", supplier: "supplierRole", employee: "employeeRole",
  affiliate: "affiliateRole", bank: "bankRole",
};

/** Sprint 5.3/5.6 (block 5.3/5.6): one screen for both سند قبض and سند
 * صرف — "محرك واحد" on the backend, one component on the frontend too,
 * parameterized by `voucherType`. The internal-transfer form
 * (settlement) is different enough (no party, no lines, two treasury
 * accounts) that it's a separate component — TransferVoucherScreen. */
export function VoucherScreen({ voucherType }: { voucherType: "receipt" | "payment" }) {
  const { t } = useLocale();
  const { me } = useAuth();
  const searchParams = useSearchParams();
  const isReceipt = voucherType === "receipt";

  const [entities, setEntities] = useState<LegalEntity[]>([]);
  const [banks, setBanks] = useState<Bank[]>([]);
  const [cashBoxes, setCashBoxes] = useState<CashBox[]>([]);
  const [custodies, setCustodies] = useState<Custody[]>([]);
  const [accounts, setAccounts] = useState<FlatAccountOption[]>([]);
  const [taxCodes, setTaxCodes] = useState<TaxCode[]>([]);
  const [costCenters, setCostCenters] = useState<CostCenter[]>([]);
  const [parties, setParties] = useState<Party[]>([]);
  const [partyInvoices, setPartyInvoices] = useState<Invoice[]>([]);

  const [legalEntityId, setLegalEntityId] = useState("");
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [treasuryKind, setTreasuryKind] = useState<TreasuryKind>("bank");
  const [treasuryId, setTreasuryId] = useState("");
  const [partyRole, setPartyRole] = useState<PartyRoleType>("customer");
  const [partyId, setPartyId] = useState("");
  const [payeeName, setPayeeName] = useState("");
  const [paymentMethod, setPaymentMethod] = useState<VoucherPaymentMethod>("cash");
  const [reference, setReference] = useState("");
  const [description, setDescription] = useState("");
  const [lines, setLines] = useState<LineDraft[]>([{ ...EMPTY_LINE }]);
  const [error, setError] = useState<string | null>(null);
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});
  const [refreshToken, setRefreshToken] = useState(0);
  const [reasonFor, setReasonFor] = useState<{ id: string; kind: "reject" | "reverse" } | null>(null);
  const [reasonText, setReasonText] = useState("");
  const [prefilled, setPrefilled] = useState(false);

  const needsEntityPicker = !!me && !me.simplified_mode;
  const showCostCenterUI = !!me && me.features.cost_centers;
  const treasuryOptions: { kind: TreasuryKind; id: string; label: string }[] = [
    ...banks.map((b) => ({ kind: "bank" as TreasuryKind, id: b.id, label: `${t("bank")}: ${b.name}` })),
    ...cashBoxes.map((c) => ({ kind: "cash_box" as TreasuryKind, id: c.id, label: `${t("cashBox")}: ${c.name}` })),
    ...custodies.map((c) => ({ kind: "custody" as TreasuryKind, id: c.id, label: `${t("custody")}: ${c.name}` })),
  ];

  useEffect(() => {
    (async () => {
      const [bankData, cashData, custodyData, tree, taxData] = await Promise.all([
        api.get<Paginated<Bank>>("/banks/"),
        api.get<Paginated<CashBox>>("/cash-boxes/"),
        api.get<Paginated<Custody>>("/custodies/"),
        api.get<AccountTreeNode[]>("/accounts/tree/"),
        api.get<Paginated<TaxCode>>("/tax-codes/"),
      ]);
      setBanks(bankData.results);
      setCashBoxes(cashData.results);
      setCustodies(custodyData.results);
      setAccounts(flattenLeafAccounts(tree));
      setTaxCodes(taxData.results);
      if (needsEntityPicker) {
        const entityData = await api.get<Paginated<LegalEntity>>("/legal-entities/");
        setEntities(entityData.results.filter((entity) => entity.entity_type !== "holding"));
      }
      if (showCostCenterUI) {
        const ccData = await api.get<Paginated<CostCenter>>("/cost-centers/");
        setCostCenters(ccData.results);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needsEntityPicker, showCostCenterUI]);

  useEffect(() => {
    api.get<Paginated<Party>>(`/parties/?role=${partyRole}`).then((data) => setParties(data.results));
  }, [partyRole]);

  useEffect(() => {
    if (!partyId) {
      setPartyInvoices([]);
      return;
    }
    api
      .get<Paginated<Invoice>>(`/invoices/?customer=${partyId}`)
      .then((data) => setPartyInvoices(data.results.filter((inv) => inv.status === "issued")));
  }, [partyId]);

  // Quick-voucher buttons elsewhere in the app (custody cycle, "+ سند
  // قبض" on an invoice, a treasury detail screen) link here with query
  // params instead of a modal — same page, pre-filled once on load.
  useEffect(() => {
    if (prefilled || treasuryOptions.length === 0) return;
    const qTreasuryKind = searchParams.get("treasury_kind") as TreasuryKind | null;
    const qTreasuryId = searchParams.get("treasury_id");
    const qParty = searchParams.get("party");
    const qPartyRole = searchParams.get("party_role") as PartyRoleType | null;
    const qInvoice = searchParams.get("invoice");
    const qAmount = searchParams.get("amount_fc");
    if (qTreasuryKind) setTreasuryKind(qTreasuryKind);
    if (qTreasuryId) setTreasuryId(qTreasuryId);
    if (qPartyRole) setPartyRole(qPartyRole);
    if (qParty) setPartyId(qParty);
    if (qInvoice) {
      setLines([
        {
          ...EMPTY_LINE, lineType: "invoice", invoice: qInvoice,
          amountFc: qAmount || "", description: "",
        },
      ]);
    }
    setPrefilled(true);
  }, [searchParams, prefilled, treasuryOptions.length]);

  const addLine = () => setLines([...lines, { ...EMPTY_LINE }]);
  const removeLine = (index: number) => setLines(lines.filter((_, i) => i !== index));
  const updateLine = (index: number, field: keyof LineDraft, value: string | boolean) => {
    setLines(lines.map((line, i) => (i === index ? { ...line, [field]: value } : line)));
  };

  const resetForm = () => {
    setLegalEntityId("");
    setDate(new Date().toISOString().slice(0, 10));
    setTreasuryKind("bank");
    setTreasuryId("");
    setPartyId("");
    setPayeeName("");
    setPaymentMethod("cash");
    setReference("");
    setDescription("");
    setLines([{ ...EMPTY_LINE }]);
    setError(null);
    setFieldErr({});
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setFieldErr({});
    const payload = {
      voucher_type: voucherType,
      ...(legalEntityId ? { legal_entity: legalEntityId } : {}),
      date,
      treasury_kind: treasuryKind,
      treasury_id: treasuryId,
      ...(partyId ? { party: partyId, party_role: partyRole } : {}),
      payee_name: payeeName,
      payment_method: paymentMethod,
      reference,
      description,
      lines: lines
        .filter((l) => l.amountFc)
        .map((l) => ({
          line_type: l.lineType,
          amount_fc: l.amountFc,
          description: l.description,
          ...(l.lineType === "invoice" ? { invoice: l.invoice, allocated_invoice_fc: l.amountFc } : {}),
          ...(l.lineType === "account"
            ? {
                account: l.account,
                ...(l.taxCode ? { tax_code: l.taxCode } : {}),
                amount_includes_tax: l.amountIncludesTax,
                ...(l.costCenter ? { cost_center: l.costCenter } : {}),
              }
            : {}),
        })),
    };
    try {
      await api.post("/vouchers/", payload);
      resetForm();
      setRefreshToken((n) => n + 1);
    } catch (err) {
      setFieldErr(fieldErrors((err as { body?: unknown }).body));
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const runAction = async (voucher: Voucher, action: string, reload: () => void) => {
    try {
      await api.post(`/vouchers/${voucher.id}/${action}/`);
    } catch (err) {
      window.alert(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
    reload();
  };

  const submitReason = async (reload: () => void) => {
    if (!reasonFor) return;
    await api.post(`/vouchers/${reasonFor.id}/${reasonFor.kind}/`, { reason: reasonText });
    setReasonFor(null);
    setReasonText("");
    reload();
  };

  return (
    <div>
      <h1>{t(isReceipt ? "receiptVouchers" : "paymentVouchers")}</h1>

      <div className="card">
        <h3>{t(isReceipt ? "createReceiptVoucher" : "createPaymentVoucher")}</h3>
        <form onSubmit={onSubmit}>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            {needsEntityPicker && (
              <div className="form-field">
                <label>{t("legalEntity")}</label>
                <select value={legalEntityId} onChange={(e) => setLegalEntityId(e.target.value)} required>
                  <option value="" disabled>—</option>
                  {entities.map((entity) => (
                    <option key={entity.id} value={entity.id}>{entity.code} — {entity.name}</option>
                  ))}
                </select>
              </div>
            )}
            <div className="form-field">
              <label>{t("voucherDate")}</label>
              <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
            </div>
            <div className="form-field">
              <label>{t("treasuryAccount")}</label>
              <select
                value={`${treasuryKind}:${treasuryId}`}
                onChange={(e) => {
                  const [kind, id] = e.target.value.split(":");
                  setTreasuryKind(kind as TreasuryKind);
                  setTreasuryId(id);
                }}
                required
              >
                <option value=":" disabled>—</option>
                {treasuryOptions.map((opt) => (
                  <option key={`${opt.kind}:${opt.id}`} value={`${opt.kind}:${opt.id}`}>{opt.label}</option>
                ))}
              </select>
            </div>
          </div>

          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "0.5rem" }}>
            <div className="form-field">
              <label>{t("partyRole")}</label>
              <select value={partyRole} onChange={(e) => setPartyRole(e.target.value as PartyRoleType)}>
                {ROLE_OPTIONS.map((role) => (
                  <option key={role} value={role}>{t(ROLE_LABEL_KEY[role])}</option>
                ))}
              </select>
            </div>
            <div className="form-field" style={{ flex: 1, minWidth: "220px" }}>
              <label>{t(isReceipt ? "receivedFrom" : "paidTo")}</label>
              <select value={partyId} onChange={(e) => setPartyId(e.target.value)}>
                <option value="">{t("none")}</option>
                {parties.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>
            {!isReceipt && !partyId && (
              <div className="form-field">
                <label>{t("payeeName")}</label>
                <input value={payeeName} onChange={(e) => setPayeeName(e.target.value)} />
              </div>
            )}
            <div className="form-field">
              <label>{t("paymentMethod")}</label>
              <select value={paymentMethod} onChange={(e) => setPaymentMethod(e.target.value as VoucherPaymentMethod)}>
                <option value="cash">{t("paymentMethodCash")}</option>
                <option value="bank_transfer">{t("paymentMethodBankTransfer")}</option>
                <option value="cheque">{t("paymentMethodCheque")}</option>
                <option value="card">{t("paymentMethodCard")}</option>
                <option value="other">{t("paymentMethodOther")}</option>
              </select>
            </div>
            <div className="form-field">
              <label>{t("reference")}</label>
              <input value={reference} onChange={(e) => setReference(e.target.value)} />
            </div>
            <div className="form-field" style={{ flex: 1, minWidth: "220px" }}>
              <label>{t("description")}</label>
              <input value={description} onChange={(e) => setDescription(e.target.value)} />
            </div>
          </div>

          <h4 style={{ marginTop: "1rem" }}>{t("payments")}</h4>
          {lines.map((line, i) => (
            <div key={i} style={{ display: "flex", gap: "0.75rem", alignItems: "end", flexWrap: "wrap", marginBottom: "0.4rem" }}>
              <div className="form-field" style={{ minWidth: "150px" }}>
                <label>{t("lineType")}</label>
                <select value={line.lineType} onChange={(e) => updateLine(i, "lineType", e.target.value)}>
                  <option value="invoice">{t("invoiceLineType")}</option>
                  <option value="on_account">{t("onAccountLineType")}</option>
                  <option value="account">{t("accountLineType")}</option>
                </select>
              </div>
              {line.lineType === "invoice" && (
                <div className="form-field" style={{ minWidth: "220px" }}>
                  <label>{t("invoiceToSettle")}</label>
                  <select value={line.invoice} onChange={(e) => updateLine(i, "invoice", e.target.value)} required>
                    <option value="" disabled>—</option>
                    {partyInvoices.map((inv) => (
                      <option key={inv.id} value={inv.id}>{inv.number} ({t("balanceDue")}: {inv.balance_fc} {inv.currency})</option>
                    ))}
                  </select>
                </div>
              )}
              {line.lineType === "account" && (
                <>
                  <div className="form-field" style={{ minWidth: "220px" }}>
                    <label>{t("account")}</label>
                    <select value={line.account} onChange={(e) => updateLine(i, "account", e.target.value)} required>
                      <option value="" disabled>—</option>
                      {accounts.map((a) => (
                        <option key={a.id} value={a.id}>{a.label}</option>
                      ))}
                    </select>
                  </div>
                  <div className="form-field" style={{ minWidth: "140px" }}>
                    <label>{t("taxCode")}</label>
                    <select value={line.taxCode} onChange={(e) => updateLine(i, "taxCode", e.target.value)}>
                      <option value="">{t("none")}</option>
                      {taxCodes.map((tc) => (
                        <option key={tc.id} value={tc.id}>{tc.code} — {tc.rate}%</option>
                      ))}
                    </select>
                  </div>
                  <label style={{ fontSize: "0.9rem", display: "flex", alignItems: "center", gap: "0.3rem" }}>
                    <input
                      type="checkbox"
                      checked={line.amountIncludesTax}
                      onChange={(e) => updateLine(i, "amountIncludesTax", e.target.checked)}
                    />
                    {t("amountIncludesTax")}
                  </label>
                  {showCostCenterUI && (
                    <div className="form-field" style={{ minWidth: "160px" }}>
                      <label>{t("costCenter")}</label>
                      <select value={line.costCenter} onChange={(e) => updateLine(i, "costCenter", e.target.value)}>
                        <option value="">{t("none")}</option>
                        {costCenters.map((cc) => (
                          <option key={cc.id} value={cc.id}>{cc.code} — {cc.name}</option>
                        ))}
                      </select>
                    </div>
                  )}
                </>
              )}
              <div className="form-field" style={{ width: "140px" }}>
                <label>{t("amount")}</label>
                <input type="number" step="0.01" value={line.amountFc} onChange={(e) => updateLine(i, "amountFc", e.target.value)} required />
              </div>
              <div className="form-field" style={{ flex: 1, minWidth: "160px" }}>
                <label>{t("description")}</label>
                <input value={line.description} onChange={(e) => updateLine(i, "description", e.target.value)} />
              </div>
              {lines.length > 1 && (
                <button type="button" className="secondary" onClick={() => removeLine(i)}>×</button>
              )}
            </div>
          ))}
          <button type="button" className="secondary" onClick={addLine} style={{ marginBottom: "1rem" }}>
            {t("addLine")}
          </button>
          <br />
          {Object.entries(fieldErr).map(([field, msg]) => (
            <p key={field} className="error-text">{field}: {msg}</p>
          ))}
          {error && <p className="error-text">{error}</p>}
          <button className="primary" type="submit">{t(isReceipt ? "createReceiptVoucher" : "createPaymentVoucher")}</button>
        </form>
      </div>

      {reasonFor && (
        <div className="card">
          <h3>{reasonFor.kind === "reject" ? t("rejectReason") : t("confirmReverseVoucher")}</h3>
          <input value={reasonText} onChange={(e) => setReasonText(e.target.value)} style={{ minWidth: "300px" }} />
          <div style={{ marginTop: "0.75rem" }}>
            <button className="primary" onClick={() => submitReason(() => setRefreshToken((n) => n + 1))}>{t("save")}</button>
            <button
              type="button" className="secondary" style={{ marginInlineStart: "0.5rem" }}
              onClick={() => { setReasonFor(null); setReasonText(""); }}
            >
              {t("cancel")}
            </button>
          </div>
        </div>
      )}

      <DataTable<Voucher>
        endpoint="/vouchers/"
        extraParams={{ voucher_type: voucherType }}
        refreshToken={refreshToken}
        hasActiveToggle={false}
        columns={[
          { key: "number", label: t("number"), sortable: true },
          { key: "voucherDate", label: t("voucherDate"), render: (row) => row.date, sortable: false },
          { key: "party_name", label: t("party"), render: (row) => row.party_name || row.payee_name },
          { key: "treasury_name", label: t("treasuryAccount") },
          { key: "total_fc", label: t("amount"), render: (row) => `${row.total_fc} ${row.currency}` },
          { key: "status", label: t("status"), render: (row) => <StatusBadge status={row.status} /> },
        ]}
        renderExtraActions={(voucher, reload) => (
          <>
            <Link href={`/dashboard/treasury/vouchers/${voucher.id}`} className="secondary" style={{ marginInlineEnd: "0.4rem" }}>
              {t("details")}
            </Link>
            {voucher.status === "draft" && (
              <button className="secondary" onClick={() => runAction(voucher, "post", reload)}>{t("postVoucher")}</button>
            )}
            {voucher.status === "pending_approval" && (
              <>
                <button className="secondary" style={{ marginInlineStart: "0.4rem" }} onClick={() => runAction(voucher, "approve", reload)}>{t("approveVoucher")}</button>
                <button className="secondary" style={{ marginInlineStart: "0.4rem" }} onClick={() => setReasonFor({ id: voucher.id, kind: "reject" })}>{t("reject")}</button>
                <button className="secondary" style={{ marginInlineStart: "0.4rem" }} onClick={() => runAction(voucher, "withdraw", reload)}>{t("withdraw")}</button>
              </>
            )}
            {voucher.status === "posted" && (
              <button className="secondary" style={{ marginInlineStart: "0.4rem" }} onClick={() => setReasonFor({ id: voucher.id, kind: "reverse" })}>{t("reverse")}</button>
            )}
          </>
        )}
      />
    </div>
  );
}
