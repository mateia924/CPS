"use client";

import { useLocale } from "@/lib/i18n";
import type { DocumentStatus } from "@/lib/types";

// Sprint 4.7 (3.18): one status pill shared by invoices and journal
// entries, so "draft/pending/approved/posted/reversed/cancelled" reads
// the same everywhere instead of each screen inventing its own colors.
const COLORS: Record<DocumentStatus, string> = {
  draft: "#8a8f98",
  pending_approval: "#b8860b",
  approved: "#2f6fb3",
  posted: "#1f9d55",
  issued: "#1f9d55",
  paid: "#1f9d55",
  reversed: "#a3492f",
  cancelled: "#a3492f",
};

export function StatusBadge({ status }: { status: DocumentStatus }) {
  const { t } = useLocale();
  const color = COLORS[status] ?? "#8a8f98";
  return (
    <span
      style={{
        display: "inline-block",
        padding: "0.15rem 0.6rem",
        borderRadius: "999px",
        fontSize: "0.8rem",
        color: "#fff",
        background: color,
        whiteSpace: "nowrap",
      }}
    >
      {t(status)}
    </span>
  );
}
