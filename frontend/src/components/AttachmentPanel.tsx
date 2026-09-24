"use client";

import { useEffect, useRef, useState } from "react";
import { API_BASE, ApiError, api, generalError } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import type { Attachment, AttachmentCategory, AttachmentTargetType, Paginated } from "@/lib/types";

export const CATEGORY_LABEL_KEY: Record<AttachmentCategory, string> = {
  fatura_original: "categoryFaturaOriginal",
  receipt: "categoryReceipt",
  contract: "categoryContract",
  bank_letter: "categoryBankLetter",
  id_document: "categoryIdDocument",
  approval_minutes: "categoryApprovalMinutes",
  bank_statement: "categoryBankStatement",
  other: "categoryOther",
};
const CATEGORIES = Object.keys(CATEGORY_LABEL_KEY) as AttachmentCategory[];

const SCAN_LABEL_KEY: Record<string, string> = {
  clean: "scanClean", pending: "scanPending", infected: "scanInfected", error: "scanError", skipped: "scanSkipped",
};
const SCAN_COLOR: Record<string, string> = {
  clean: "var(--success)", pending: "var(--warning)", infected: "var(--danger)", error: "var(--danger)",
  skipped: "var(--muted)",
};

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** docs/SYSTEM_ANALYSIS.md 3.17 — one component for every detail
 * screen. `mode` only affects labels/expectations at this stage (every
 * behavioral difference — versioning vs. plain addition, delete never
 * existing at all — is already enforced server-side regardless of what
 * the client sends, per the backend's own VERSIONED_TARGETS split). */
export function AttachmentPanel({
  targetType,
  targetId,
}: {
  targetType: AttachmentTargetType;
  targetId: string;
}) {
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [count, setCount] = useState(0);
  const [category, setCategory] = useState<AttachmentCategory>("other");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [showOlder, setShowOlder] = useState(false);
  const [voidingId, setVoidingId] = useState<string | null>(null);
  const [voidReason, setVoidReason] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const cameraInputRef = useRef<HTMLInputElement>(null);

  const load = () => {
    api
      .get<Paginated<Attachment>>(`/attachments/?target_type=${targetType}&target_id=${targetId}`)
      .then((data) => {
        setAttachments(data.results);
        setCount(data.results.filter((a) => a.status === "active").length);
      });
  };

  useEffect(() => {
    // The counter badge (📎 N) needs a count even before the panel is
    // ever opened.
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetType, targetId]);

  const upload = async (file: File) => {
    setError(null);
    setUploading(true);
    const formData = new FormData();
    formData.append("target_type", targetType);
    formData.append("target_id", targetId);
    formData.append("category", category);
    formData.append("description", description);
    formData.append("file", file);
    try {
      await api.upload("/attachments/", formData);
      setDescription("");
      load();
    } catch (err) {
      setError(generalError(err instanceof ApiError ? err.body : null, "Could not upload this file."));
    } finally {
      setUploading(false);
    }
  };

  const onFileChosen = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) upload(file);
    e.target.value = "";
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) upload(file);
  };

  const download = async (attachment: Attachment) => {
    const { token } = await api.post<{ token: string }>(`/attachments/${attachment.id}/link/`);
    window.open(`${API_BASE}/attachments/${attachment.id}/download/?token=${encodeURIComponent(token)}`, "_blank");
  };

  const submitVoid = async () => {
    if (!voidingId || voidReason.trim().length < 3) return;
    await api.post(`/attachments/${voidingId}/void/`, { reason: voidReason });
    setVoidingId(null);
    setVoidReason("");
    load();
  };

  const supersededIds = new Set(attachments.filter((a) => a.supersedes).map((a) => a.supersedes));
  const current = attachments.filter((a) => a.status === "active" && !supersededIds.has(a.id));
  const older = attachments.filter((a) => a.status === "voided" || supersededIds.has(a.id));

  const row = (attachment: Attachment) => (
    <tr key={attachment.id} style={attachment.status === "voided" ? { opacity: 0.55 } : undefined}>
      <td>{t(CATEGORY_LABEL_KEY[attachment.category])}</td>
      <td>{attachment.original_name}</td>
      <td>{formatSize(attachment.size)}</td>
      <td>
        <span
          style={{
            display: "inline-block", padding: "0.1rem 0.5rem", borderRadius: "var(--radius-pill)",
            fontSize: "0.75rem", color: "var(--color-on-primary)", background: SCAN_COLOR[attachment.scan_status],
          }}
        >
          {t(SCAN_LABEL_KEY[attachment.scan_status])}
        </span>
      </td>
      <td style={{ fontSize: "0.8rem", color: "var(--muted)" }}>
        {attachment.uploaded_by_email} · {new Date(attachment.uploaded_at).toLocaleDateString()}
      </td>
      <td style={{ whiteSpace: "nowrap" }}>
        <button className="secondary" onClick={() => download(attachment)}>
          {t("downloadAttachment")}
        </button>
        {attachment.status === "active" && (
          <button
            className="secondary"
            style={{ marginInlineStart: "0.4rem" }}
            onClick={() => setVoidingId(attachment.id)}
          >
            {t("voidAttachment")}
          </button>
        )}
      </td>
    </tr>
  );

  return (
    <div className="card">
      <button type="button" className="secondary" onClick={() => setOpen((v) => !v)}>
        📎 {t("attachments")} ({count})
      </button>

      {open && (
        <div style={{ marginTop: "0.75rem" }}>
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            onClick={() => fileInputRef.current?.click()}
            style={{
              border: `2px dashed ${dragOver ? "var(--primary)" : "var(--border)"}`,
              borderRadius: "8px", padding: "1rem", textAlign: "center", cursor: "pointer",
              marginBottom: "0.75rem",
            }}
          >
            {uploading ? t("checking") : t("dragDropHint")}
          </div>
          <input ref={fileInputRef} type="file" hidden onChange={onFileChosen} />
          <input
            ref={cameraInputRef}
            type="file"
            accept="image/*"
            capture="environment"
            hidden
            onChange={onFileChosen}
          />

          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end", marginBottom: "0.75rem" }}>
            <div className="form-field">
              <label>{t("categoryLabel")}</label>
              <select value={category} onChange={(e) => setCategory(e.target.value as AttachmentCategory)}>
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {t(CATEGORY_LABEL_KEY[c])}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-field" style={{ flex: 1, minWidth: "160px" }}>
              <label>{t("description")}</label>
              <input value={description} onChange={(e) => setDescription(e.target.value)} />
            </div>
            <button type="button" className="secondary" onClick={() => cameraInputRef.current?.click()}>
              {t("captureWithCamera")}
            </button>
          </div>
          {error && <p className="error-text">{error}</p>}

          {voidingId && (
            <div className="card" style={{ marginBottom: "0.75rem" }}>
              <p>{t("confirmVoidAttachment")}</p>
              <input value={voidReason} onChange={(e) => setVoidReason(e.target.value)} style={{ minWidth: "260px" }} />
              <div style={{ marginTop: "0.5rem" }}>
                <button className="primary" onClick={submitVoid}>
                  {t("save")}
                </button>
                <button
                  type="button"
                  className="secondary"
                  style={{ marginInlineStart: "0.5rem" }}
                  onClick={() => {
                    setVoidingId(null);
                    setVoidReason("");
                  }}
                >
                  {t("cancel")}
                </button>
              </div>
            </div>
          )}

          {current.length === 0 ? (
            <p style={{ color: "var(--muted)" }}>{t("noAttachments")}</p>
          ) : (
            <table>
              <tbody>{current.map(row)}</tbody>
            </table>
          )}

          {older.length > 0 && (
            <details style={{ marginTop: "0.75rem" }}>
              <summary style={{ cursor: "pointer" }} onClick={() => setShowOlder((v) => !v)}>
                {t("olderVersions")} ({older.length})
              </summary>
              {showOlder && (
                <table style={{ marginTop: "0.5rem" }}>
                  <tbody>{older.map(row)}</tbody>
                </table>
              )}
            </details>
          )}
        </div>
      )}
    </div>
  );
}
