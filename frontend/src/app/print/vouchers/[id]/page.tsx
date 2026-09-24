"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { amountInWordsAr } from "@/lib/numberToWordsAr";
import type { LegalEntity, Voucher } from "@/lib/types";

const DOC_TYPE_LABEL: Record<string, string> = {
  receipt: "voucherReceiptDocType",
  payment: "voucherPaymentDocType",
  settlement: "voucherSettlementDocType",
};

export default function VoucherPrintPage() {
  const { id } = useParams<{ id: string }>();
  const { t } = useLocale();
  const [voucher, setVoucher] = useState<Voucher | null>(null);
  const [entity, setEntity] = useState<LegalEntity | null>(null);

  useEffect(() => {
    api.get<Voucher>(`/vouchers/${id}/`).then(async (v) => {
      setVoucher(v);
      const entityData = await api.get<LegalEntity>(`/legal-entities/${v.legal_entity}/`);
      setEntity(entityData);
    });
  }, [id]);

  if (!voucher || !entity) return null;

  const isReceipt = voucher.voucher_type === "receipt";
  const profile = entity.effective_profile;
  const addressLine = [profile.building_number, profile.street, profile.district, profile.city]
    .filter(Boolean)
    .join("، ");

  return (
    <div>
      <div className="print-actions">
        <button className="primary" onClick={() => window.print()}>{t("printButton")}</button>
      </div>
      <div className="print-page">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
          <div style={{ display: "flex", gap: "0.75rem", alignItems: "start" }}>
            <img src="/brand/cps-logo-horizontal.svg" alt="CPS" style={{ height: 48 }} />
            <div>
              <h2 style={{ margin: 0 }}>{entity.name}</h2>
              {entity.tax_number && <p>{t("taxNumber")}: {entity.tax_number}</p>}
              {addressLine && <p>{addressLine}</p>}
            </div>
          </div>
          <div style={{ textAlign: "end" }}>
            <h2>{t(DOC_TYPE_LABEL[voucher.voucher_type])}</h2>
            <p>{t("number")}: {voucher.number}</p>
            <p>{t("voucherDate")}: {voucher.date}</p>
          </div>
        </div>

        <hr style={{ margin: "1.5rem 0", border: "none", borderTop: "1px solid var(--border)" }} />

        <p>
          <strong>{t(isReceipt ? "receivedFrom" : "paidTo")}:</strong>{" "}
          {voucher.party_name || voucher.payee_name || "—"}
        </p>
        <p><strong>{t("treasuryAccount")}:</strong> {voucher.treasury_name}</p>
        {voucher.counter_treasury_name && (
          <p><strong>{t("destinationAccount")}:</strong> {voucher.counter_treasury_name}</p>
        )}
        <p><strong>{t("description")}:</strong> {voucher.description || "—"}</p>
        {voucher.reference && <p><strong>{t("reference")}:</strong> {voucher.reference}</p>}

        <p style={{ marginTop: "1rem", fontSize: "1.2rem" }}>
          <strong>{t("grandTotal")}: {voucher.total_fc} {voucher.currency}</strong>
        </p>
        <p>{t("amountInWords")}: {amountInWordsAr(voucher.total_fc, voucher.currency)}</p>

        <div className="print-signatures">
          <div>{t("signatureReceiver")}</div>
          <div>{t("signatureAccountant")}</div>
          <div>{t("signatureManager")}</div>
        </div>
      </div>
    </div>
  );
}
