"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { AttachmentPanel } from "@/components/AttachmentPanel";
import { Money } from "@/components/Money";
import { StatusBadge } from "@/components/StatusBadge";
import { useLocale } from "@/lib/i18n";
import { formatDate } from "@/lib/date";
import type { JournalEntry } from "@/lib/types";

/** Sprint 6 (block 6.0, item 2): a real detail screen for one journal
 * entry — so the link from an invoice/voucher's "القيد الناتج" leads
 * somewhere, not just a raw id. */
export default function JournalEntryDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { t } = useLocale();
  const [entry, setEntry] = useState<JournalEntry | null>(null);

  useEffect(() => {
    api.get<JournalEntry>(`/journal-entries/${id}/`).then(setEntry);
  }, [id]);

  if (!entry) return null;

  return (
    <div>
      <button className="secondary" onClick={() => router.push("/dashboard/accounting/journal-entries")}>
        ← {t("back")}
      </button>

      <h1 style={{ marginTop: "1rem" }}>
        {entry.number || `(${t("draft")})`} <StatusBadge status={entry.status} />
      </h1>

      <div className="card">
        <p>{t("date")}: {formatDate(entry.date, "form")}</p>
        <p>{t("legalEntity")}: {entry.legal_entity_name}</p>
        <p>{t("description")}: {entry.memo}</p>
        {entry.reference && <p>{t("reference")}: {entry.reference}</p>}
        {entry.reverses && <p>{t("reverses")}: {entry.reverses}</p>}
      </div>

      <div className="card">
        <h3>{t("lines")}</h3>
        <table>
          <thead>
            <tr>
              <th>{t("account")}</th>
              <th>{t("description")}</th>
              <th>{t("debitFc")}</th>
              <th>{t("creditFc")}</th>
            </tr>
          </thead>
          <tbody>
            {entry.lines.map((line) => (
              <tr key={line.id}>
                <td>{line.account_code} — {line.account_name}</td>
                <td>{line.description}</td>
                <td>{line.debit_fc !== "0.00" ? <Money amount={line.debit_fc} /> : ""}</td>
                <td>{line.credit_fc !== "0.00" ? <Money amount={line.credit_fc} /> : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <AttachmentPanel targetType="journal_entry" targetId={entry.id} />
    </div>
  );
}
