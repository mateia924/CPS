import { formatMoney } from "@/lib/money";

/** Sprint 6 (block 6.0, item 4): the `.money` (tabular-nums, LTR
 * isolate) span wrapped around formatMoney() — the one way a financial
 * amount is ever rendered in this app. */
export function Money({ amount, currency }: { amount: string | number | null | undefined; currency?: string }) {
  return <span className="money">{formatMoney(amount, currency)}</span>;
}
