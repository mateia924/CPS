"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { Money } from "@/components/Money";
import { useLocale } from "@/lib/i18n";
import type { ReconciliationDashboardRow } from "@/lib/types";

// Sprint 6.9 (sprint-6.md, "التسوية البنكية" — a debt from 5.5.2 paid
// off here): every bank's reconciliation status at a glance, instead
// of opening each bank's own detail page one at a time. The actual
// import/reconcile actions still live on BankReconciliationCard (bank
// detail page) — this screen links there rather than duplicating it.
export default function BankReconciliationDashboardPage() {
  const { t } = useLocale();
  const [rows, setRows] = useState<ReconciliationDashboardRow[] | null>(null);

  useEffect(() => {
    api.get<ReconciliationDashboardRow[]>("/reconciliation-dashboard/").then(setRows);
  }, []);

  return (
    <div>
      <h1>{t("bankReconciliationDashboardNav")}</h1>

      <div className="card">
        {!rows ? null : rows.length === 0 ? (
          <p style={{ color: "var(--muted)" }}>{t("noData")}</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>{t("bankNameColumn")}</th>
                <th>{t("currency")}</th>
                <th>{t("lastStatementEndColumn")}</th>
                <th>{t("reconciledRatioColumn")}</th>
                <th>{t("unmatchedStatementItemsColumn")}</th>
                <th>{t("unmatchedBookLinesColumn")}</th>
                <th>{t("differenceColumn")}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.bank_id}>
                  <td>{row.bank_name}</td>
                  <td>{row.currency}</td>
                  <td>{row.last_statement_end || "—"}</td>
                  <td>{row.has_statement ? `${Math.round(row.reconciled_ratio * 100)}%` : "—"}</td>
                  <td>{row.unmatched_statement_items}</td>
                  <td>{row.unmatched_book_lines}</td>
                  <td>
                    <Money amount={row.difference} currency={row.currency} />
                  </td>
                  <td>
                    <Link href={`/dashboard/treasury/banks/${row.bank_id}`} className="secondary">
                      {t("importReconcileAction")}
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
