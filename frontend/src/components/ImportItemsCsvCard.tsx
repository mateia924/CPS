"use client";

import { useState } from "react";
import { api, ApiError, generalError } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { WarningsBanner } from "@/components/WarningsBanner";

interface ImportResult {
  created: number;
  errors: { row: number; error: string }[];
}

const CSV_TEMPLATE =
  "كود,اسم,نوع,فئة,وحدة,باركود,حد إعادة الطلب,تكلفة افتراضية\n" +
  "SKU-001,صنف تجريبي,مخزني,,,,,\n";

/** Sprint 7.1 (block spec, item 3): CSV import for items, with a
 * per-row Arabic error report — ProductViewSet.import_csv's own
 * frontend counterpart. Downloading the template is a plain client-
 * side Blob, no API round trip needed for two static lines. */
export function ImportItemsCsvCard({ onImported }: { onImported: () => void }) {
  const { t } = useLocale();
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const downloadTemplate = () => {
    const blob = new Blob([CSV_TEMPLATE], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "items-template.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setUploading(true);
    setError(null);
    setResult(null);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const data = await api.upload<ImportResult>("/products/import_csv/", formData);
      setResult(data);
      setFile(null);
      if (data.created > 0) onImported();
    } catch (err) {
      setError(generalError(err instanceof ApiError ? err.body : null, t("couldNotSave")));
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="card">
      <h3>{t("importCsv")}</h3>
      <form onSubmit={onSubmit} style={{ display: "flex", gap: "0.75rem", alignItems: "center", flexWrap: "wrap" }}>
        <button type="button" className="secondary" onClick={downloadTemplate}>
          {t("importCsvTemplate")}
        </button>
        <input
          type="file"
          accept=".csv,text/csv"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          aria-label={t("importCsvFile")}
        />
        <button className="primary" type="submit" disabled={!file || uploading}>
          {t("importCsvSubmit")}
        </button>
      </form>
      <WarningsBanner warnings={error ? [error] : []} variant="error" />
      {result && (
        <div style={{ marginTop: "0.75rem" }}>
          <p>
            {result.created} {t("importCsvCreatedCount")}
            {result.errors.length > 0 && <>، {result.errors.length} {t("importCsvFailedCount")}</>}
          </p>
          {result.errors.length > 0 && (
            <ul>
              {result.errors.map((e) => (
                <li key={e.row} style={{ color: "var(--danger)" }}>
                  {t("importCsvRowPrefix")} {e.row}: {e.error}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
