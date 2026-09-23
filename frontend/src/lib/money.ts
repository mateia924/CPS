/** Sprint 6 (block 6.0, item 4): one money-formatting function for the
 * whole app — thousands separator, two decimal places, tabular
 * (monospaced) Latin digits so columns of numbers actually line up.
 * Never renders a raw numeric string directly in a financial screen.
 */
export function formatMoney(amount: string | number | null | undefined, currency?: string): string {
  if (amount === null || amount === undefined || amount === "") return "—";
  const value = typeof amount === "string" ? Number(amount) : amount;
  if (Number.isNaN(value)) return "—";
  const formatted = new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
  return currency ? `${formatted} ${currency}` : formatted;
}
