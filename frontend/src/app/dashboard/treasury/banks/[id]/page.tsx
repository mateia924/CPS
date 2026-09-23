"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { AttachmentPanel } from "@/components/AttachmentPanel";
import { BankReconciliationCard } from "@/components/BankReconciliationCard";
import { TreasuryMovementsCard } from "@/components/TreasuryMovementsCard";
import { useLocale } from "@/lib/i18n";
import type { Bank } from "@/lib/types";

export default function BankDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { t } = useLocale();
  const [bank, setBank] = useState<Bank | null>(null);

  useEffect(() => {
    api.get<Bank>(`/banks/${id}/`).then(setBank);
  }, [id]);

  if (!bank) return null;

  return (
    <div>
      <button className="secondary" onClick={() => router.push("/dashboard/treasury/banks")}>
        ← {t("back")}
      </button>

      <h1 style={{ marginTop: "1rem" }}>{bank.name}</h1>

      <div className="card">
        <p>{t("bankName")}: {bank.bank_name || "—"}</p>
        <p>{t("accountNumber")}: {bank.account_number || "—"}</p>
        <p>{t("currency")}: {bank.currency}</p>
        <Link
          href={`/dashboard/treasury/vouchers/receipt?treasury_kind=bank&treasury_id=${bank.id}`}
          className="primary"
          style={{ display: "inline-block", marginTop: "0.5rem" }}
        >
          {t("quickReceiptFor")}
        </Link>
        <Link
          href={`/dashboard/treasury/vouchers/payment?treasury_kind=bank&treasury_id=${bank.id}`}
          className="secondary"
          style={{ display: "inline-block", marginTop: "0.5rem", marginInlineStart: "0.5rem" }}
        >
          {t("quickPaymentFor")}
        </Link>
      </div>

      <TreasuryMovementsCard kind="bank" id={bank.id} />

      <BankReconciliationCard bankId={bank.id} />

      <AttachmentPanel targetType="bank" targetId={bank.id} />
    </div>
  );
}
