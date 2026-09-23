"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import type { LedgerStatement, TreasuryKind } from "@/lib/types";

const ENDPOINT: Record<TreasuryKind, string> = {
  bank: "banks", cash_box: "cash-boxes", custody: "custodies",
};

/** Sprint 5.4 (block 5.4): "الحركات" tab on the bank/cash-box/custody
 * detail screen — GET /api/{kind}s/{id}/movements/, same ledger_lines()
 * shape as PartyStatementCard. */
export function TreasuryMovementsCard({ kind, id }: { kind: TreasuryKind; id: string }) {
  const { t } = useLocale();
  const [statement, setStatement] = useState<LedgerStatement | null>(null);

  useEffect(() => {
    api.get<LedgerStatement>(`/${ENDPOINT[kind]}/${id}/movements/`).then(setStatement);
  }, [kind, id]);

  if (!statement) return null;

  return (
    <div className="card">
      <h3>{t("movementsTab")}</h3>
      <p>{t("openingBalance")}: {statement.opening_balance_fc}</p>
      <p>{t("closingBalance")}: {statement.closing_balance_fc}</p>

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
                <td>{line.debit_fc !== "0.00" ? line.debit_fc : ""}</td>
                <td>{line.credit_fc !== "0.00" ? line.credit_fc : ""}</td>
                <td>{line.running_balance_fc}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
