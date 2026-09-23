"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { AttachmentPanel } from "@/components/AttachmentPanel";
import type { AffiliateParty, LegalEntity, Paginated } from "@/lib/types";

export default function AffiliatesPage() {
  const { t } = useLocale();
  const [entities, setEntities] = useState<LegalEntity[]>([]);
  const [editing, setEditing] = useState<AffiliateParty | null>(null);
  const [name, setName] = useState("");
  const [legalEntityId, setLegalEntityId] = useState("");
  const [taxNumber, setTaxNumber] = useState("");
  const [defaultCurrency, setDefaultCurrency] = useState("SAR");
  const [error, setError] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);

  useEffect(() => {
    api.get<Paginated<LegalEntity>>("/legal-entities/").then((data) => setEntities(data.results));
  }, []);

  const startEdit = (party: AffiliateParty) => {
    setEditing(party);
    setName(party.name);
    setLegalEntityId(party.legal_entity || "");
    setTaxNumber(party.tax_number);
    setDefaultCurrency(party.default_currency);
    setError(null);
  };

  const cancelEdit = () => {
    setEditing(null);
    setName("");
    setLegalEntityId("");
    setTaxNumber("");
    setDefaultCurrency("SAR");
    setError(null);
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const payload = {
      name,
      legal_entity: legalEntityId,
      tax_number: taxNumber,
      default_currency: defaultCurrency,
    };
    try {
      if (editing) {
        await api.patch(`/parties/affiliates/${editing.id}/`, payload);
      } else {
        await api.post("/parties/affiliates/", payload);
      }
      cancelEdit();
      setRefreshToken((n) => n + 1);
    } catch {
      setError("Could not save this affiliate company — a matching legal entity is required.");
    }
  };

  return (
    <div>
      <h1>{t("affiliatesNav")}</h1>

      <div className="card">
        <h3>{editing ? t("edit") : t("add")}</h3>
        <form onSubmit={onSubmit}>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <div className="form-field">
              <label>{t("name")}</label>
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </div>
            <div className="form-field">
              <label>{t("matchingLegalEntity")}</label>
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
                <label>{t("taxNumber")}</label>
                <input value={taxNumber} onChange={(e) => setTaxNumber(e.target.value)} />
              </div>
              <div className="form-field">
                <label>{t("defaultCurrency")}</label>
                <input value={defaultCurrency} onChange={(e) => setDefaultCurrency(e.target.value)} maxLength={3} />
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

      {editing && <AttachmentPanel targetType="party" targetId={editing.id} />}

      <DataTable<AffiliateParty>
        endpoint="/parties/affiliates/"
        refreshToken={refreshToken}
        onEdit={startEdit}
        columns={[
          { key: "code", label: t("code"), sortable: true },
          { key: "name", label: t("name"), sortable: true },
        ]}
      />
    </div>
  );
}
