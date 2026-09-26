"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api, fieldErrors, generalError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { Money } from "@/components/Money";
import { StatusBadge } from "@/components/StatusBadge";
import { WarningsBanner } from "@/components/WarningsBanner";
import type { Bank, CashBox, Custody, LegalEntity, Paginated, TreasuryKind, Voucher } from "@/lib/types";

/** Sprint 5.4 (block 5.4) — سند تسوية / تحويل داخلي: two treasury
 * accounts, no party, no lines — genuinely a different shape from
 * receipt/payment, so it gets its own screen (and its own create
 * endpoint, POST /vouchers/transfer/) rather than another branch
 * inside VoucherScreen. */
export function TransferVoucherScreen() {
  const { t } = useLocale();
  const { me } = useAuth();
  const searchParams = useSearchParams();

  const [entities, setEntities] = useState<LegalEntity[]>([]);
  const [banks, setBanks] = useState<Bank[]>([]);
  const [cashBoxes, setCashBoxes] = useState<CashBox[]>([]);
  const [custodies, setCustodies] = useState<Custody[]>([]);

  const [legalEntityId, setLegalEntityId] = useState("");
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [treasuryKind, setTreasuryKind] = useState<TreasuryKind>("bank");
  const [treasuryId, setTreasuryId] = useState("");
  const [counterTreasuryKind, setCounterTreasuryKind] = useState<TreasuryKind>("bank");
  const [counterTreasuryId, setCounterTreasuryId] = useState("");
  const [amountFc, setAmountFc] = useState("");
  const [counterAmountFc, setCounterAmountFc] = useState("");
  const [reference, setReference] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});
  const [warnings, setWarnings] = useState<string[]>([]);
  const [refreshToken, setRefreshToken] = useState(0);
  const [reasonFor, setReasonFor] = useState<string | null>(null);
  const [reasonText, setReasonText] = useState("");
  const [prefilled, setPrefilled] = useState(false);

  const needsEntityPicker = !!me && !me.simplified_mode;
  const treasuryOptions: { kind: TreasuryKind; id: string; label: string; currency: string }[] = [
    ...banks.map((b) => ({ kind: "bank" as TreasuryKind, id: b.id, label: `${t("bank")}: ${b.name}`, currency: b.currency })),
    ...cashBoxes.map((c) => ({ kind: "cash_box" as TreasuryKind, id: c.id, label: `${t("cashBox")}: ${c.name}`, currency: c.currency })),
    ...custodies.map((c) => ({ kind: "custody" as TreasuryKind, id: c.id, label: `${t("custody")}: ${c.name}`, currency: c.currency })),
  ];
  const sourceCurrency = treasuryOptions.find((o) => o.kind === treasuryKind && o.id === treasuryId)?.currency;
  const destCurrency = treasuryOptions.find((o) => o.kind === counterTreasuryKind && o.id === counterTreasuryId)?.currency;
  const needsCounterAmount = !!sourceCurrency && !!destCurrency && sourceCurrency !== destCurrency;

  useEffect(() => {
    (async () => {
      const [bankData, cashData, custodyData] = await Promise.all([
        api.get<Paginated<Bank>>("/banks/"),
        api.get<Paginated<CashBox>>("/cash-boxes/"),
        api.get<Paginated<Custody>>("/custodies/"),
      ]);
      setBanks(bankData.results);
      setCashBoxes(cashData.results);
      setCustodies(custodyData.results);
      if (needsEntityPicker) {
        const entityData = await api.get<Paginated<LegalEntity>>("/legal-entities/");
        setEntities(entityData.results.filter((entity) => entity.entity_type !== "holding"));
        // Sprint 6.0.1-B item 6: default to the user's own primary branch.
        if (me?.legal_entity_ids[0]) setLegalEntityId((prev) => prev || me.legal_entity_ids[0]);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needsEntityPicker]);

  useEffect(() => {
    if (prefilled || treasuryOptions.length === 0) return;
    const qTreasuryKind = searchParams.get("treasury_kind") as TreasuryKind | null;
    const qTreasuryId = searchParams.get("treasury_id");
    const qCounterKind = searchParams.get("counter_treasury_kind") as TreasuryKind | null;
    const qCounterId = searchParams.get("counter_treasury_id");
    if (qTreasuryKind) setTreasuryKind(qTreasuryKind);
    if (qTreasuryId) setTreasuryId(qTreasuryId);
    if (qCounterKind) setCounterTreasuryKind(qCounterKind);
    if (qCounterId) setCounterTreasuryId(qCounterId);
    setPrefilled(true);
  }, [searchParams, prefilled, treasuryOptions.length]);

  const resetForm = () => {
    setLegalEntityId("");
    setDate(new Date().toISOString().slice(0, 10));
    setTreasuryId("");
    setCounterTreasuryId("");
    setAmountFc("");
    setCounterAmountFc("");
    setReference("");
    setDescription("");
    setError(null);
    setFieldErr({});
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setFieldErr({});
    const payload = {
      ...(legalEntityId ? { legal_entity: legalEntityId } : {}),
      date,
      treasury_kind: treasuryKind,
      treasury_id: treasuryId,
      counter_treasury_kind: counterTreasuryKind,
      counter_treasury_id: counterTreasuryId,
      amount_fc: amountFc,
      ...(needsCounterAmount && counterAmountFc ? { counter_amount_fc: counterAmountFc } : {}),
      reference,
      description,
    };
    try {
      await api.post("/vouchers/transfer/", payload);
      resetForm();
      setRefreshToken((n) => n + 1);
    } catch (err) {
      setFieldErr(fieldErrors((err as { body?: unknown }).body));
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const runAction = async (voucher: Voucher, action: string, reload: () => void) => {
    try {
      const result = await api.post<Voucher>(`/vouchers/${voucher.id}/${action}/`);
      setWarnings(result.warnings || []);
    } catch (err) {
      window.alert(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
    reload();
  };

  const submitReason = async (reload: () => void) => {
    if (!reasonFor) return;
    const result = await api.post<Voucher>(`/vouchers/${reasonFor}/reverse/`, { reason: reasonText });
    setWarnings(result.warnings || []);
    setReasonFor(null);
    setReasonText("");
    reload();
  };

  return (
    <div>
      <h1>{t("settlementVouchers")}</h1>
      <WarningsBanner warnings={warnings} />

      <div className="card">
        <h3>{t("createTransferVoucher")}</h3>
        <form onSubmit={onSubmit}>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <div className="form-field">
              <label>{t("voucherDate")}</label>
              <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
            </div>
          </div>

          {needsEntityPicker && (
            <details style={{ marginTop: "0.75rem" }}>
              <summary style={{ cursor: "pointer" }}>{t("advanced")}</summary>
              <div className="form-field" style={{ marginTop: "0.75rem", maxWidth: "320px" }}>
                <label>{t("legalEntity")}</label>
                <select value={legalEntityId} onChange={(e) => setLegalEntityId(e.target.value)} required>
                  <option value="" disabled>—</option>
                  {entities.map((entity) => (
                    <option key={entity.id} value={entity.id}>{entity.code} — {entity.name}</option>
                  ))}
                </select>
              </div>
            </details>
          )}

          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "0.5rem" }}>
            <div className="form-field">
              <label>{t("sourceAccount")}</label>
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
                  <option key={`s-${opt.kind}:${opt.id}`} value={`${opt.kind}:${opt.id}`}>{opt.label}</option>
                ))}
              </select>
            </div>
            <div className="form-field">
              <label>{t("destinationAccount")}</label>
              <select
                value={`${counterTreasuryKind}:${counterTreasuryId}`}
                onChange={(e) => {
                  const [kind, id] = e.target.value.split(":");
                  setCounterTreasuryKind(kind as TreasuryKind);
                  setCounterTreasuryId(id);
                }}
                required
              >
                <option value=":" disabled>—</option>
                {treasuryOptions.map((opt) => (
                  <option key={`d-${opt.kind}:${opt.id}`} value={`${opt.kind}:${opt.id}`}>{opt.label}</option>
                ))}
              </select>
            </div>
            <div className="form-field">
              <label>{t("amount")} ({sourceCurrency || "—"})</label>
              <input type="number" step="0.01" value={amountFc} onChange={(e) => setAmountFc(e.target.value)} required />
            </div>
            {needsCounterAmount && (
              <div className="form-field">
                <label>{t("counterAmount")} ({destCurrency})</label>
                <input type="number" step="0.01" value={counterAmountFc} onChange={(e) => setCounterAmountFc(e.target.value)} required />
              </div>
            )}
            <div className="form-field">
              <label>{t("reference")}</label>
              <input value={reference} onChange={(e) => setReference(e.target.value)} />
            </div>
            <div className="form-field" style={{ flex: 1, minWidth: "220px" }}>
              <label>{t("description")}</label>
              <input value={description} onChange={(e) => setDescription(e.target.value)} />
            </div>
          </div>

          <br />
          {Object.entries(fieldErr).map(([field, msg]) => (
            <p key={field} className="error-text">{field}: {msg}</p>
          ))}
          {error && <p className="error-text">{error}</p>}
          <button className="primary" type="submit">{t("createTransferVoucher")}</button>
        </form>
      </div>

      {reasonFor && (
        <div className="card">
          <h3>{t("confirmReverseVoucher")}</h3>
          <input value={reasonText} onChange={(e) => setReasonText(e.target.value)} style={{ minWidth: "300px" }} />
          <div style={{ marginTop: "0.75rem" }}>
            <button className="primary" onClick={() => submitReason(() => setRefreshToken((n) => n + 1))}>{t("save")}</button>
            <button type="button" className="secondary" style={{ marginInlineStart: "0.5rem" }} onClick={() => { setReasonFor(null); setReasonText(""); }}>{t("cancel")}</button>
          </div>
        </div>
      )}

      <DataTable<Voucher>
        endpoint="/vouchers/"
        extraParams={{ voucher_type: "settlement" }}
        refreshToken={refreshToken}
        hasActiveToggle={false}
        columns={[
          { key: "number", label: t("number"), sortable: true },
          { key: "date", label: t("voucherDate") },
          { key: "treasury_name", label: t("sourceAccount") },
          { key: "counter_treasury_name", label: t("destinationAccount") },
          { key: "total_fc", label: t("amount"), render: (row) => <Money amount={row.total_fc} currency={row.currency} /> },
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
                <button className="secondary" style={{ marginInlineStart: "0.4rem" }} onClick={() => runAction(voucher, "withdraw", reload)}>{t("withdraw")}</button>
              </>
            )}
            {voucher.status === "posted" && (
              <button className="secondary" style={{ marginInlineStart: "0.4rem" }} onClick={() => setReasonFor(voucher.id)}>{t("reverse")}</button>
            )}
          </>
        )}
      />
    </div>
  );
}
