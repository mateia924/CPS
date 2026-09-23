"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import type { AuditLogEntry, Paginated } from "@/lib/types";

/** Sprint 5.7 (CFO_REVIEW_1 F10): "سجل التغييرات" tab — GET /api/
 * audit-log/?target_type=&target_id=, this tenant's own AuditLog rows
 * for one record. `targetType` matches AuditLog.target_type exactly as
 * the backend wrote it (e.g. "sales.Invoice", "voucher", "journal_entry" —
 * see each app's log_action() calls), not the AttachmentTargetType
 * short names. */
export function ChangeHistoryTab({ targetType, targetId }: { targetType: string; targetId: string }) {
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  const [entries, setEntries] = useState<AuditLogEntry[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!open || loaded) return;
    api
      .get<Paginated<AuditLogEntry>>(`/audit-log/?target_type=${encodeURIComponent(targetType)}&target_id=${targetId}`)
      .then((data) => {
        setEntries(data.results);
        setLoaded(true);
      });
  }, [open, loaded, targetType, targetId]);

  return (
    <div className="card">
      <h3 style={{ cursor: "pointer" }} onClick={() => setOpen((v) => !v)}>
        {t("changeHistoryTab")} {open ? "▲" : "▼"}
      </h3>
      {open && (
        entries.length === 0 && loaded ? (
          <p style={{ color: "var(--muted)" }}>{t("noChangeHistory")}</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>{t("date")}</th>
                <th>{t("actor")}</th>
                <th>{t("action")}</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <tr key={entry.id}>
                  <td>{new Date(entry.created_at).toLocaleString()}</td>
                  <td>{entry.actor_id || "—"}</td>
                  <td>{entry.action}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      )}
    </div>
  );
}
