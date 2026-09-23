"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import type { Bank, CashBox, LedgerStatement, Paginated } from "@/lib/types";

export default function DashboardHome() {
  const { user, tenant, me } = useAuth();
  const { t } = useLocale();
  const [cashByCurrency, setCashByCurrency] = useState<Record<string, number> | null>(null);

  useEffect(() => {
    if (!me?.features.treasury) return;
    (async () => {
      const [banks, cashBoxes] = await Promise.all([
        api.get<Paginated<Bank>>("/banks/"),
        api.get<Paginated<CashBox>>("/cash-boxes/"),
      ]);
      const accounts = [
        ...banks.results.map((b) => ({ kind: "banks", id: b.id, currency: b.currency })),
        ...cashBoxes.results.map((c) => ({ kind: "cash-boxes", id: c.id, currency: c.currency })),
      ];
      const balances = await Promise.all(
        accounts.map((a) => api.get<LedgerStatement>(`/${a.kind}/${a.id}/movements/`))
      );
      const totals: Record<string, number> = {};
      accounts.forEach((account, i) => {
        totals[account.currency] = (totals[account.currency] || 0) + parseFloat(balances[i].closing_balance_fc);
      });
      setCashByCurrency(totals);
    })();
  }, [me]);

  return (
    <div>
      <div className="card">
        <h1>
          {t("welcome")}, {user?.first_name || user?.email}
        </h1>
        <p>{tenant?.name}</p>
      </div>

      {cashByCurrency && (
        <div className="card">
          <h3>{t("cashOnHandCard")}</h3>
          {Object.keys(cashByCurrency).length === 0 ? (
            <p style={{ color: "var(--muted)" }}>{t("noData")}</p>
          ) : (
            Object.entries(cashByCurrency).map(([currency, total]) => (
              <p key={currency} style={{ fontSize: "1.4rem", margin: "0.2rem 0" }}>
                {total.toFixed(2)} {currency}
              </p>
            ))
          )}
        </div>
      )}
    </div>
  );
}
