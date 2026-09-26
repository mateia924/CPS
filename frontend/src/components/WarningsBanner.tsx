"use client";

import { useState } from "react";

// Sprint 6.9.1 (item B): every warnings[] the API returns (credit
// limit, stale exchange rate, etc.) must reach the user somewhere —
// before this, only fiscal-years' own checklist showed anything like
// this; every other screen silently dropped the array. Stays visible
// until dismissed or the screen is left — never a toast that
// disappears on its own.
export function WarningsBanner({ warnings }: { warnings: string[] }) {
  const [dismissed, setDismissed] = useState(false);

  if (dismissed || warnings.length === 0) return null;

  return (
    <div
      style={{
        background: "var(--warning-bg)",
        color: "var(--warning)",
        border: "1px solid var(--warning)",
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
          color: "var(--warning)",
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
