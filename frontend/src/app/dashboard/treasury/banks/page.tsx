"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { AttachmentPanel } from "@/components/AttachmentPanel";
import type { Bank, LegalEntity, Paginated } from "@/lib/types";

export default function BanksPage() {
  const { t } = useLocale();
  const [entities, setEntities] = useState<LegalEntity[]>([]);
  const [editing, setEditing] = useState<Bank | null>(null);
  const [legalEntityId, setLegalEntityId] = useState("");
  const [name, setName] = useState("");
  const [bankName, setBankName] = useState("");
  const [accountNumber, setAccountNumber] = useState("");
  const [iban, setIban] = useState("");
  const [swift, setSwift] = useState("");
  const [currency, setCurrency] = useState("SAR");
  const [error, setError] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);

  useEffect(() => {
    api.get<Paginated<LegalEntity>>("/legal-entities/").then((data) => setEntities(data.results));
  }, []);

  const startEdit = (bank: Bank) => {
    setEditing(bank);
    setLegalEntityId(bank.legal_entity);
    setName(bank.name);
    setBankName(bank.bank_name);
    setAccountNumber(bank.account_number);
    setIban(bank.iban);
    setSwift(bank.swift);
    setCurrency(bank.currency);
    setError(null);
  };

  const cancelEdit = () => {
    setEditing(null);
    setLegalEntityId("");
    setName("");
    setBankName("");
    setAccountNumber("");
    setIban("");
    setSwift("");
    setCurrency("SAR");
    setError(null);
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const payload = {
      legal_entity: legalEntityId,
      name,
      bank_name: bankName,
      account_number: accountNumber,
      iban,
      swift,
      currency,
    };
    try {
      if (editing) {
        await api.patch(`/banks/${editing.id}/`, payload);
      } else {
        await api.post("/banks/", payload);
      }
      cancelEdit();
      setRefreshToken((n) => n + 1);
    } catch {
      setError("Could not save this bank account.");
    }
  };

  return (
    <div>
      <h1>{t("banks")}</h1>

      <div className="card">
        <h3>{editing ? t("edit") : t("add")}</h3>
        <form onSubmit={onSubmit}>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <div className="form-field">
              <label>{t("name")}</label>
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </div>
            <div className="form-field">
              <label>{t("legalEntity")}</label>
              <select value={legalEntityId} onChange={(e) => setLegalEntityId(e.target.value)} required>
                <option value="" disabled>
                  —
                </option>
                {entities.map((entity) => (
                  <option key={entity.id} value={entity.id}>
                    {entity.code} — {entity.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <details style={{ marginTop: "0.75rem" }}>
            <summary style={{ cursor: "pointer" }}>{t("advanced")}</summary>
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
              <div className="form-field">
                <label>{t("bankName")}</label>
                <input value={bankName} onChange={(e) => setBankName(e.target.value)} />
              </div>
              <div className="form-field">
                <label>{t("accountNumber")}</label>
                <input value={accountNumber} onChange={(e) => setAccountNumber(e.target.value)} />
              </div>
              <div className="form-field">
                <label>IBAN</label>
                <input value={iban} onChange={(e) => setIban(e.target.value)} />
              </div>
              <div className="form-field">
                <label>SWIFT</label>
                <input value={swift} onChange={(e) => setSwift(e.target.value)} />
              </div>
              <div className="form-field">
                <label>{t("currency")}</label>
                <input value={currency} onChange={(e) => setCurrency(e.target.value)} maxLength={3} />
              </div>
            </div>
          </details>

          {error && <p className="error-text">{error}</p>}
          <button className="primary" type="submit" style={{ marginTop: "0.75rem" }}>
            {editing ? t("saveChanges") : t("add")}
          </button>
          {editing && (
            <button
              type="button"
              className="secondary"
              style={{ marginTop: "0.75rem", marginInlineStart: "0.5rem" }}
              onClick={cancelEdit}
            >
              {t("cancel")}
            </button>
          )}
        </form>
      </div>

      {editing && <AttachmentPanel targetType="bank" targetId={editing.id} />}

      <DataTable<Bank>
        endpoint="/banks/"
        refreshToken={refreshToken}
        onEdit={startEdit}
        columns={[
          { key: "name", label: t("name"), sortable: true },
          { key: "bank_name", label: t("bankName") },
          { key: "account_number", label: t("accountNumber") },
          { key: "currency", label: t("currency") },
        ]}
      />
    </div>
  );
}
