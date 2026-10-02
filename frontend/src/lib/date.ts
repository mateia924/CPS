/** Sprint 6.6.6 (docs/prompts/sprint-6.6.md): one date-formatting
 * function for the whole app — never `.toLocaleDateString()` with no
 * arguments (browser-locale-dependent: the live "9/30/2026" bug in
 * the asset transfer log was exactly this, on a US-locale browser)
 * and never `Date.toString()`. UTC getters throughout (never the
 * local-timezone ones) — this project's own backend default is
 * TIME_ZONE=UTC (config/settings.py), and a plain "YYYY-MM-DD" date
 * string (issue_date, date, …) parses as UTC midnight; reading it
 * back with local getters can silently shift the displayed day by
 * one depending on the browser's own timezone offset.
 *
 * `style`: "table" (default) — ISO `YYYY-MM-DD`, sortable as plain
 * text, consistent with every other tabular display in this project.
 * "form" — `DD/MM/YYYY`, for a human reading a form or a printed
 * document, never for a table column.
 */
export function formatDate(
  date: string | Date | null | undefined,
  style: "table" | "form" = "table"
): string {
  if (!date) return "—";
  const d = typeof date === "string" ? new Date(date) : date;
  if (Number.isNaN(d.getTime())) return "—";
  const year = d.getUTCFullYear();
  const month = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return style === "form" ? `${day}/${month}/${year}` : `${year}-${month}-${day}`;
}

/** Same rationale as `formatDate` above, for a full timestamp
 * (`created_at`, `generated_at`, …) — `.toLocaleString()` with no
 * arguments has the exact same browser-locale-dependent bug as
 * `.toLocaleDateString()`, just for date+time together. */
export function formatDateTime(
  date: string | Date | null | undefined,
  style: "table" | "form" = "table"
): string {
  if (!date) return "—";
  const d = typeof date === "string" ? new Date(date) : date;
  if (Number.isNaN(d.getTime())) return "—";
  const hours = String(d.getUTCHours()).padStart(2, "0");
  const minutes = String(d.getUTCMinutes()).padStart(2, "0");
  return `${formatDate(d, style)} ${hours}:${minutes}`;
}
