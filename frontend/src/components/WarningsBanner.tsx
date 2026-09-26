"use client";

import { useEffect, useState } from "react";

// Sprint 6.9.1 (item B): every warnings[] the API returns (credit
// limit, stale exchange rate, etc.) must reach the user somewhere —
// before this, only fiscal-years' own checklist showed anything like
// this; every other screen silently dropped the array. Stays visible
// until dismissed or the screen is left — never a toast that
// disappears on its own.
//
// Sprint 6.5.6 (SYSTEM_ANALYSIS §3.18 rule): `variant="error"` reuses
// the exact same banner for a form's own non-field errors (network
// failure, {detail: "..."}, an unrecognized shape) — the one place in
// SYSTEM_ANALYSIS.md's own rule an error "لا يرتبط بحقل" belongs,
// styled in --danger instead of --warning. A field-level error never
// goes here — see FormField, which renders it under the field itself.
export function WarningsBanner({
  warnings,
  variant = "warning",
}: {
  warnings: string[];
  variant?: "warning" | "error";
}) {
  const [dismissed, setDismissed] = useState(false);
  // A fresh warnings/error array (a new submit, a new action) always
  // reappears even if a previous, unrelated one was dismissed — only
  // the exact same still-visible content stays dismissed.
  useEffect(() => setDismissed(false), [warnings]);

  if (dismissed || warnings.length === 0) return null;

  const colorVar = variant === "error" ? "--danger" : "--warning";
  const bgVar = variant === "error" ? "--danger-bg" : "--warning-bg";

  return (
    <div
      style={{
        background: `var(${bgVar})`,
        color: `var(${colorVar})`,
        border: `1px solid var(${colorVar})`,
        borderRadius: "var(--radius)",
        padding: "0.6rem 0.9rem",
        margin: "0.5rem 0",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "flex-start",
        gap: "0.75rem",
      }}
    >
      <ul style={{ margin: 0, paddingInlineStart: "1.1rem" }}>
        {warnings.map((warning, i) => (
          <li key={i}>{warning}</li>
        ))}
      </ul>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        aria-label="dismiss"
        style={{
          background: "none",
          border: "none",
          color: `var(${colorVar})`,
          cursor: "pointer",
          fontSize: "1rem",
          lineHeight: 1,
        }}
      >
        ×
      </button>
    </div>
  );
}
