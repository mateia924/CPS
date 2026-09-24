"use client";

import { useLocale } from "@/lib/i18n";
import type { DocumentStatus } from "@/lib/types";

// Sprint 4.7 (3.18), tokens per BRAND.md §2.5 (sprint 6.0.1): one status
// pill shared by invoices and journal entries — text/background pairs
// read exclusively from --status-* tokens (tokens.css), never a literal
// color, so every document status reads the same everywhere.
const STATUS_TOKENS: Record<DocumentStatus, { color: string; bg: string }> = {
  draft: { color: "var(--status-draft)", bg: "var(--status-draft-bg)" },
  pending_approval: { color: "var(--status-pending)", bg: "var(--status-pending-bg)" },
  approved: { color: "var(--status-approved)", bg: "var(--status-approved-bg)" },
  posted: { color: "var(--status-posted)", bg: "var(--status-posted-bg)" },
  issued: { color: "var(--status-posted)", bg: "var(--status-posted-bg)" },
  paid: { color: "var(--status-posted)", bg: "var(--status-posted-bg)" },
  reversed: { color: "var(--status-reversed)", bg: "var(--status-reversed-bg)" },
  cancelled: { color: "var(--status-void)", bg: "var(--status-void-bg)" },
  // Sprint 6.3: OpeningBalanceEntry's own terminal REJECTED.
  rejected: { color: "var(--status-void)", bg: "var(--status-void-bg)" },
  // Sprint 6.4: RecurringEntry's own terminal COMPLETED.
  completed: { color: "var(--status-posted)", bg: "var(--status-posted-bg)" },
};

export function StatusBadge({ status }: { status: DocumentStatus }) {
  const { t } = useLocale();
  const tokens = STATUS_TOKENS[status] ?? STATUS_TOKENS.draft;
  return (
    <span
      style={{
        display: "inline-block",
        padding: "0.15rem 0.6rem",
        borderRadius: "var(--radius-pill)",
        fontSize: "0.8rem",
        fontWeight: 600,
        color: tokens.color,
        background: tokens.bg,
        whiteSpace: "nowrap",
      }}
    >
      {t(status)}
    </span>
  );
}
