"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import type { ExchangeRate } from "@/lib/types";

export default function ExchangeRatesPage() {
  const { t } = useLocale();
  const [fromCurrency, setFromCurrency] = useState("USD");
  const [toCurrency, setToCurrency] = useState("SAR");
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [rate, setRate] = useState("");
  const [source, setSource] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
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
    } catch {
      setError("Could not save this exchange rate.");
    }
  };

  return (
    <div>
      <h1>{t("exchangeRatesNav")}</h1>

      <div className="card">
        <h3>{t("addExchangeRate")}</h3>
        <form onSubmit={onSubmit}>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <div className="form-field">
              <label>{t("fromCurrency")}</label>
              <input value={fromCurrency} onChange={(e) => setFromCurrency(e.target.value)} maxLength={3} required />
            </div>
            <div className="form-field">
              <label>{t("toCurrency")}</label>
              <input value={toCurrency} onChange={(e) => setToCurrency(e.target.value)} maxLength={3} required />
            </div>
            <div className="form-field">
              <label>{t("date")}</label>
              <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
            </div>
            <div className="form-field">
              <label>{t("rate")}</label>
              <input type="number" step="0.00000001" value={rate} onChange={(e) => setRate(e.target.value)} required />
            </div>
            <div className="form-field">
              <label>{t("rateSource")}</label>
              <input value={source} onChange={(e) => setSource(e.target.value)} />
            </div>
          </div>
          {error && <p className="error-text">{error}</p>}
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
      />
    </div>
  );
}
