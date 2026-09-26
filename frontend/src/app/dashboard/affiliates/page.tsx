"use client";

import { useEffect, useState } from "react";
import { api, fieldErrors, generalError } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { AttachmentPanel } from "@/components/AttachmentPanel";
import { FormField } from "@/components/FormField";
import { EMPTY_STRUCTURED_ADDRESS, StructuredAddressFieldset } from "@/components/StructuredAddressFieldset";
import { WarningsBanner } from "@/components/WarningsBanner";
import type { AffiliateParty, LegalEntity, Paginated, StructuredAddressFields } from "@/lib/types";

export default function AffiliatesPage() {
  const { t } = useLocale();
  const [entities, setEntities] = useState<LegalEntity[]>([]);
  const [editing, setEditing] = useState<AffiliateParty | null>(null);
  const [name, setName] = useState("");
  const [legalEntityId, setLegalEntityId] = useState("");
  const [taxNumber, setTaxNumber] = useState("");
  const [defaultCurrency, setDefaultCurrency] = useState("SAR");
  const [structuredAddress, setStructuredAddress] = useState<StructuredAddressFields>(EMPTY_STRUCTURED_ADDRESS);
  const [error, setError] = useState<string | null>(null);
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});
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
    setStructuredAddress({
      building_number: party.building_number, street: party.street, district: party.district,
      city: party.city, postal_code: party.postal_code, short_address: party.short_address,
    });
    setError(null);
    setFieldErr({});
  };

  const cancelEdit = () => {
    setEditing(null);
    setName("");
    setLegalEntityId("");
    setTaxNumber("");
    setDefaultCurrency("SAR");
    setStructuredAddress(EMPTY_STRUCTURED_ADDRESS);
    setError(null);
    setFieldErr({});
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setFieldErr({});
    const payload = {
      name,
      legal_entity: legalEntityId,
      tax_number: taxNumber,
      default_currency: defaultCurrency,
      ...structuredAddress,
    };
    try {
      if (editing) {
        await api.patch(`/parties/affiliates/${editing.id}/`, payload);
      } else {
        await api.post("/parties/affiliates/", payload);
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
      <h1>{t("affiliatesNav")}</h1>

      <div className="card">
        <h3>{editing ? t("edit") : t("add")}</h3>
        <form onSubmit={onSubmit}>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <FormField name="name" required error={fieldErr.name}>
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </FormField>
            <FormField name="legal_entity" label={t("matchingLegalEntity")} required error={fieldErr.legal_entity}>
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
          </div>

          <details style={{ marginTop: "0.75rem" }}>
            <summary style={{ cursor: "pointer" }}>{t("advanced")}</summary>
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
              <FormField name="tax_number" error={fieldErr.tax_number}>
                <input value={taxNumber} onChange={(e) => setTaxNumber(e.target.value)} />
              </FormField>
              <FormField name="default_currency" error={fieldErr.default_currency}>
                <input value={defaultCurrency} onChange={(e) => setDefaultCurrency(e.target.value)} maxLength={3} />
              </FormField>
            </div>
          </details>

          <StructuredAddressFieldset value={structuredAddress} onChange={setStructuredAddress} fieldErr={fieldErr} />

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
