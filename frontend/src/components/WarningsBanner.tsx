"use client";

import { useEffect, useState } from "react";

// Sprint 6.5.8 (UAT bugfix): several backend service-layer catches
// return {"detail": str(exc)} for a caught django.core.exceptions.
// ValidationError — Django's own __str__ for it is `repr(list(self))`,
// e.g. "['الاعتماد الاضطراري يشترط سببًا إلزاميًا']", a Python list
// literal leaking into the UI verbatim instead of the clean message.
// Recognized once here rather than at every backend call site, so
// every screen using this one shared component is fixed at once — a
// message that merely happens to start/end with brackets for real
// never matches this narrow "whole string is a Python list of quoted
// strings" shape, so it's never touched.
const PY_LIST_OF_STRINGS = /^\[\s*(?:'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")(?:\s*,\s*(?:'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"))*\s*\]$/s;
const QUOTED_ITEM = /'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"/g;

function cleanWarningText(text: string): string {
  const trimmed = text.trim();
  if (!PY_LIST_OF_STRINGS.test(trimmed)) return text;
  const items: string[] = [];
  let m: RegExpExecArray | null;
  QUOTED_ITEM.lastIndex = 0;
  while ((m = QUOTED_ITEM.exec(trimmed)) !== null) {
    items.push((m[1] ?? m[2]).replace(/\\(['"\\])/g, "$1"));
  }
  return items.length > 0 ? items.join("، ") : text;
}

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
          <li key={i}>{cleanWarningText(warning)}</li>
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
