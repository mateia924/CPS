"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { AttachmentPanel } from "@/components/AttachmentPanel";
import { TreasuryMovementsCard } from "@/components/TreasuryMovementsCard";
import { useLocale } from "@/lib/i18n";
import type { CashBox } from "@/lib/types";

export default function CashBoxDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { t } = useLocale();
  const [cashBox, setCashBox] = useState<CashBox | null>(null);

  useEffect(() => {
    api.get<CashBox>(`/cash-boxes/${id}/`).then(setCashBox);
  }, [id]);

  if (!cashBox) return null;

  return (
    <div>
      <button className="secondary" onClick={() => router.push("/dashboard/treasury/cash-boxes")}>
        ← {t("back")}
      </button>

      <h1 style={{ marginTop: "1rem" }}>{cashBox.name}</h1>

      <div className="card">
        <p>{t("currency")}: {cashBox.currency}</p>
        <p>{t("cashBoxMaxBalance")}: {cashBox.max_balance ?? "—"}</p>
        <Link
          href={`/dashboard/treasury/vouchers/receipt?treasury_kind=cash_box&treasury_id=${cashBox.id}`}
          className="primary"
          style={{ display: "inline-block", marginTop: "0.5rem" }}
        >
          {t("quickReceiptFor")}
        </Link>
        <Link
          href={`/dashboard/treasury/vouchers/payment?treasury_kind=cash_box&treasury_id=${cashBox.id}`}
          className="secondary"
          style={{ display: "inline-block", marginTop: "0.5rem", marginInlineStart: "0.5rem" }}
        >
          {t("quickPaymentFor")}
        </Link>
      </div>

      <TreasuryMovementsCard kind="cash_box" id={cashBox.id} />

      <AttachmentPanel targetType="cash_box" targetId={cashBox.id} />
    </div>
  );
}
