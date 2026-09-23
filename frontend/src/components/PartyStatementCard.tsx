"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import type { PartyRoleType, PartyStatement } from "@/lib/types";

/** Sprint 5.4/5.6 (block 5.4/5.6): "كشف الحساب" tab on a party's
 * detail screen — one card, reused by the customer and employee detail
 * pages (supplier/affiliate have no detail page yet — see the Decision
 * Log note in docs/sprints/5-summary.md). Backed by GET /api/parties/
 * {id}/statement/?role=. */
export function PartyStatementCard({ partyId, role }: { partyId: string; role: PartyRoleType }) {
  const { t } = useLocale();
  const [statement, setStatement] = useState<PartyStatement | null>(null);

  useEffect(() => {
    api.get<PartyStatement>(`/parties/${partyId}/statement/?role=${role}`).then(setStatement);
  }, [partyId, role]);

  if (!statement) return null;

  return (
    <div className="card">
      <h3>{t("statementTab")}</h3>
      <p>{t("openingBalance")}: {statement.opening_balance}</p>
      <p>{t("closingBalance")}: {statement.closing_balance}</p>

      {statement.lines.length === 0 ? (
        <p style={{ color: "var(--muted)" }}>{t("noData")}</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>{t("date")}</th>
              <th>{t("description")}</th>
              <th>{t("debitFc")}</th>
              <th>{t("creditFc")}</th>
              <th>{t("runningBalance")}</th>
            </tr>
          </thead>
          <tbody>
            {statement.lines.map((line) => (
              <tr key={`${line.entry_id}-${line.date}`}>
                <td>{line.date}</td>
                <td>{line.description}</td>
                <td>{line.debit !== "0.00" ? line.debit : ""}</td>
                <td>{line.credit !== "0.00" ? line.credit : ""}</td>
                <td>{line.running_balance}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {statement.open_invoices.length > 0 && (
        <>
          <h4 style={{ marginTop: "1rem" }}>{t("openInvoices")}</h4>
          <table>
            <thead>
              <tr>
                <th>{t("number")}</th>
                <th>{t("dueDate")}</th>
                <th>{t("total")}</th>
                <th>{t("balanceDue")}</th>
              </tr>
            </thead>
            <tbody>
              {statement.open_invoices.map((inv) => (
                <tr key={inv.id}>
                  <td>{inv.number}</td>
                  <td>{inv.due_date || "—"}</td>
                  <td>{inv.total} {inv.currency}</td>
                  <td>{inv.balance_fc} {inv.currency}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
