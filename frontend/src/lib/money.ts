/** Sprint 6 (block 6.0, item 4; finalized 6.0.1-B): one money-formatting
 * function for the whole app — thousands separator, two decimal places,
 * tabular (monospaced) Latin digits so columns of numbers actually line
 * up, currency code after the number, negative sign "−" (not
 * parens). Never render a raw numeric string directly in a financial
 * screen — go through this (or <Money>).
 */
export function formatMoney(amount: string | number | null | undefined, currency?: string): string {
  if (amount === null || amount === undefined || amount === "") return "—";
  const value = typeof amount === "string" ? Number(amount) : amount;
  if (Number.isNaN(value)) return "—";
  const formatted = new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
    .format(value)
    .replace(/^-/, "−");
  return currency ? `${formatted} ${currency}` : formatted;
}
