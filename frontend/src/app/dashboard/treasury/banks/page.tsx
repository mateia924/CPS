"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, fieldErrors, generalError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { AttachmentPanel } from "@/components/AttachmentPanel";
import { FormField } from "@/components/FormField";
import { WarningsBanner } from "@/components/WarningsBanner";
import type { Bank, LegalEntity, Paginated } from "@/lib/types";

export default function BanksPage() {
  const { t } = useLocale();
  const { me } = useAuth();
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
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});
  const [refreshToken, setRefreshToken] = useState(0);

  useEffect(() => {
    api.get<Paginated<LegalEntity>>("/legal-entities/").then((data) => {
      setEntities(data.results);
      // Sprint 6.0.1-B item 6: default to the user's own primary branch.
      if (me?.legal_entity_ids[0]) setLegalEntityId((prev) => prev || me.legal_entity_ids[0]);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    setFieldErr({});
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setFieldErr({});
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
    } catch (err) {
      setFieldErr(fieldErrors((err as { body?: unknown }).body));
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  return (
    <div>
      <h1>{t("banks")}</h1>

      <div className="card">
        <h3>{editing ? t("edit") : t("add")}</h3>
        <form onSubmit={onSubmit}>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <FormField name="name" label={t("name")} required error={fieldErr.name}>
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </FormField>
          </div>

          <details style={{ marginTop: "0.75rem" }}>
            <summary style={{ cursor: "pointer" }}>{t("advanced")}</summary>
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
              <FormField name="legal_entity" label={t("legalEntity")} required error={fieldErr.legal_entity}>
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
              </FormField>
              <FormField name="bank_name" label={t("bankName")} error={fieldErr.bank_name}>
                <input value={bankName} onChange={(e) => setBankName(e.target.value)} />
              </FormField>
              <FormField name="account_number" label={t("accountNumber")} error={fieldErr.account_number}>
                <input value={accountNumber} onChange={(e) => setAccountNumber(e.target.value)} />
              </FormField>
              <FormField name="iban" label="IBAN" error={fieldErr.iban}>
                <input value={iban} onChange={(e) => setIban(e.target.value)} />
              </FormField>
              <FormField name="swift" label="SWIFT" error={fieldErr.swift}>
                <input value={swift} onChange={(e) => setSwift(e.target.value)} />
              </FormField>
              <FormField name="currency" label={t("currency")} error={fieldErr.currency}>
                <input value={currency} onChange={(e) => setCurrency(e.target.value)} maxLength={3} />
              </FormField>
            </div>
          </details>

          <WarningsBanner warnings={error ? [error] : []} variant="error" />
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
        renderExtraActions={(bank) => (
          <Link href={`/dashboard/treasury/banks/${bank.id}`} className="secondary">
            {t("details")}
          </Link>
        )}
      />
    </div>
  );
}
