"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { AttachmentPanel } from "@/components/AttachmentPanel";
import { TreasuryMovementsCard } from "@/components/TreasuryMovementsCard";
import { useLocale } from "@/lib/i18n";
import type { Custody } from "@/lib/types";

// Sprint 5.4 (block 5.4): "أزرار دورة العهدة" — each one is the
// existing transfer/payment engine with a pre-filled query string, not
// a new backend endpoint (صرف/استرداد = internal transfer with this
// custody as destination/source; تسوية = an ordinary payment voucher
// from this custody). The buttons themselves are new here in 5.6 since
// they open a real voucher form, which didn't exist before this block.
export default function CustodyDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { t } = useLocale();
  const [custody, setCustody] = useState<Custody | null>(null);

  useEffect(() => {
    api.get<Custody>(`/custodies/${id}/`).then(setCustody);
  }, [id]);

  if (!custody) return null;

  return (
    <div>
      <button className="secondary" onClick={() => router.push("/dashboard/treasury/custodies")}>
        ← {t("back")}
      </button>

      <h1 style={{ marginTop: "1rem" }}>{custody.name}</h1>

      <div className="card">
        <p>{t("currency")}: {custody.currency}</p>
        <p>{t("custodyLimit")}: {custody.limit_amount ?? "—"}</p>

        <Link
          href={`/dashboard/treasury/vouchers/settlement?counter_treasury_kind=custody&counter_treasury_id=${custody.id}`}
          className="primary"
          style={{ display: "inline-block", marginTop: "0.5rem" }}
        >
          {t("disburseToCustody")}
        </Link>
        <Link
          href={`/dashboard/treasury/vouchers/payment?treasury_kind=custody&treasury_id=${custody.id}`}
          className="secondary"
          style={{ display: "inline-block", marginTop: "0.5rem", marginInlineStart: "0.5rem" }}
        >
          {t("settleCustody")}
        </Link>
        <Link
          href={`/dashboard/treasury/vouchers/settlement?treasury_kind=custody&treasury_id=${custody.id}`}
          className="secondary"
          style={{ display: "inline-block", marginTop: "0.5rem", marginInlineStart: "0.5rem" }}
        >
          {t("refundCustody")}
        </Link>
      </div>

      <TreasuryMovementsCard kind="custody" id={custody.id} />

      <AttachmentPanel targetType="custody" targetId={custody.id} />
    </div>
  );
}
