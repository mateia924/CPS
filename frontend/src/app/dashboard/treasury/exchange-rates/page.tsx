"use client";

import { useState } from "react";
import { api, fieldErrors, generalError } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { AttachmentPanel } from "@/components/AttachmentPanel";
import { FormField } from "@/components/FormField";
import { WarningsBanner } from "@/components/WarningsBanner";
import type { ExchangeRate } from "@/lib/types";

export default function ExchangeRatesPage() {
  const { t } = useLocale();
  const [fromCurrency, setFromCurrency] = useState("USD");
  const [toCurrency, setToCurrency] = useState("SAR");
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [rate, setRate] = useState("");
  const [source, setSource] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});
  const [refreshToken, setRefreshToken] = useState(0);
  const [attachmentsFor, setAttachmentsFor] = useState<string | null>(null);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setFieldErr({});
    try {
      await api.post("/exchange-rates/", {
        from_currency: fromCurrency,
        to_currency: toCurrency,
        date,
        rate,
        source,
      });
      setRate("");
      setSource("");
      setRefreshToken((n) => n + 1);
    } catch (err) {
      setFieldErr(fieldErrors((err as { body?: unknown }).body));
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  return (
    <div>
      <h1>{t("exchangeRatesNav")}</h1>

      <div className="card">
        <h3>{t("addExchangeRate")}</h3>
        <form onSubmit={onSubmit}>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <FormField name="from_currency" label={t("fromCurrency")} required error={fieldErr.from_currency}>
              <input value={fromCurrency} onChange={(e) => setFromCurrency(e.target.value)} maxLength={3} required />
            </FormField>
            <FormField name="to_currency" label={t("toCurrency")} required error={fieldErr.to_currency}>
              <input value={toCurrency} onChange={(e) => setToCurrency(e.target.value)} maxLength={3} required />
            </FormField>
            <FormField name="date" label={t("date")} required error={fieldErr.date}>
              <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
            </FormField>
            <FormField name="rate" label={t("rate")} required error={fieldErr.rate}>
              <input type="number" step="0.00000001" value={rate} onChange={(e) => setRate(e.target.value)} required />
            </FormField>
            <FormField name="source" label={t("rateSource")} error={fieldErr.source}>
              <input value={source} onChange={(e) => setSource(e.target.value)} />
            </FormField>
          </div>
          <WarningsBanner warnings={error ? [error] : []} variant="error" />
          <button className="primary" type="submit" style={{ marginTop: "0.75rem" }}>
            {t("add")}
          </button>
        </form>
      </div>

      <DataTable<ExchangeRate>
        endpoint="/exchange-rates/"
        refreshToken={refreshToken}
        hasActiveToggle={false}
        columns={[
          { key: "date", label: t("date"), sortable: true },
          { key: "from_currency", label: t("fromCurrency") },
          { key: "to_currency", label: t("toCurrency") },
          { key: "rate", label: t("rate") },
          { key: "source", label: t("rateSource") },
        ]}
        renderExtraActions={(row) => (
          <button
            className="secondary"
            onClick={() => setAttachmentsFor(attachmentsFor === row.id ? null : row.id)}
          >
            📎 {t("attachments")}
          </button>
        )}
      />

      {attachmentsFor && <AttachmentPanel targetType="exchange_rate" targetId={attachmentsFor} />}
    </div>
  );
}
