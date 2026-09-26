"use client";

import { useState } from "react";
import { api, fieldErrors, generalError } from "@/lib/api";
import { checkPartyDuplicate } from "@/lib/duplicateCheck";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { AttachmentPanel } from "@/components/AttachmentPanel";
import { FormField } from "@/components/FormField";
import { EMPTY_STRUCTURED_ADDRESS, StructuredAddressFieldset } from "@/components/StructuredAddressFieldset";
import { WarningsBanner } from "@/components/WarningsBanner";
import type { StructuredAddressFields, SupplierParty } from "@/lib/types";

const ROLE_LABEL_KEY: Record<string, string> = {
  customer: "customerRole",
  supplier: "supplierRole",
  employee: "employeeRole",
  affiliate: "affiliateRole",
  bank: "bankRole",
};

export default function SuppliersPage() {
  const { t } = useLocale();
  const [editing, setEditing] = useState<SupplierParty | null>(null);
  const [name, setName] = useState("");
  const [partyType, setPartyType] = useState<"individual" | "organization">("organization");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [taxNumber, setTaxNumber] = useState("");
  const [nationalIdOrCr, setNationalIdOrCr] = useState("");
  const [defaultCurrency, setDefaultCurrency] = useState("SAR");
  const [paymentTermsDays, setPaymentTermsDays] = useState("");
  const [iban, setIban] = useState("");
  const [notes, setNotes] = useState("");
  const [structuredAddress, setStructuredAddress] = useState<StructuredAddressFields>(EMPTY_STRUCTURED_ADDRESS);
  const [error, setError] = useState<string | null>(null);
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});
  const [checkingDuplicate, setCheckingDuplicate] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);

  const startEdit = (party: SupplierParty) => {
    setEditing(party);
    setName(party.name);
    setPartyType(party.party_type);
    setPhone(party.phone);
    setEmail(party.email);
    setTaxNumber(party.tax_number);
    setNationalIdOrCr(party.national_id_or_cr);
    setDefaultCurrency(party.default_currency);
    setPaymentTermsDays(party.payment_terms_days?.toString() || "");
    setIban(party.iban || "");
    setNotes(party.notes);
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
    setPartyType("organization");
    setPhone("");
    setEmail("");
    setTaxNumber("");
    setNationalIdOrCr("");
    setDefaultCurrency("SAR");
    setPaymentTermsDays("");
    setIban("");
    setNotes("");
    setStructuredAddress(EMPTY_STRUCTURED_ADDRESS);
    setError(null);
    setFieldErr({});
  };

  const buildPayload = () => ({
    name,
    party_type: partyType,
    phone,
    email,
    tax_number: taxNumber,
    national_id_or_cr: nationalIdOrCr,
    default_currency: defaultCurrency,
    payment_terms_days: paymentTermsDays ? Number(paymentTermsDays) : null,
    iban,
    notes,
    ...structuredAddress,
  });

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setFieldErr({});

    if (!editing && (taxNumber || nationalIdOrCr)) {
      setCheckingDuplicate(true);
      let existing;
      try {
        existing = await checkPartyDuplicate(taxNumber, nationalIdOrCr);
      } finally {
        setCheckingDuplicate(false);
      }
      if (existing && !existing.roles.some((r) => r.role === "supplier")) {
        const roleNames = existing.roles.map((r) => t(ROLE_LABEL_KEY[r.role])).join("، ");
        const confirmed = window.confirm(
          `${t("alreadyRegisteredAs")} "${existing.name}" (${roleNames}). ${t("confirmAddRoleToo")}`
        );
        if (!confirmed) return;
        await api.post(`/parties/${existing.id}/add-role/`, { role: "supplier" });
        cancelEdit();
        setRefreshToken((n) => n + 1);
        return;
      }
    }

    try {
      if (editing) {
        await api.patch(`/parties/suppliers/${editing.id}/`, buildPayload());
      } else {
        await api.post("/parties/suppliers/", buildPayload());
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
      <h1>{t("suppliers")}</h1>

      <div className="card">
        <h3>{editing ? t("edit") : t("add")}</h3>
        <form onSubmit={onSubmit}>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <FormField name="name" required error={fieldErr.name}>
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </FormField>
            <FormField name="party_type" label={t("partyType")} error={fieldErr.party_type}>
              <select value={partyType} onChange={(e) => setPartyType(e.target.value as typeof partyType)}>
                <option value="organization">{t("partyTypeOrganization")}</option>
                <option value="individual">{t("individual")}</option>
              </select>
            </FormField>
            <FormField name="phone" error={fieldErr.phone}>
              <input value={phone} onChange={(e) => setPhone(e.target.value)} />
            </FormField>
            <FormField name="email" error={fieldErr.email}>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </FormField>
          </div>

          <details style={{ marginTop: "0.75rem" }}>
            <summary style={{ cursor: "pointer" }}>{t("advanced")}</summary>
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
              <FormField name="tax_number" error={fieldErr.tax_number}>
                <input value={taxNumber} onChange={(e) => setTaxNumber(e.target.value)} />
              </FormField>
              <FormField name="national_id_or_cr" error={fieldErr.national_id_or_cr}>
                <input value={nationalIdOrCr} onChange={(e) => setNationalIdOrCr(e.target.value)} />
              </FormField>
              <FormField name="default_currency" error={fieldErr.default_currency}>
                <input value={defaultCurrency} onChange={(e) => setDefaultCurrency(e.target.value)} maxLength={3} />
              </FormField>
              <FormField name="payment_terms_days" error={fieldErr.payment_terms_days}>
                <input type="number" value={paymentTermsDays} onChange={(e) => setPaymentTermsDays(e.target.value)} />
              </FormField>
              <FormField name="iban" label="IBAN" error={fieldErr.iban}>
                <input value={iban} onChange={(e) => setIban(e.target.value)} />
              </FormField>
              <FormField name="notes" error={fieldErr.notes} style={{ flex: 1, minWidth: "200px" }}>
                <input value={notes} onChange={(e) => setNotes(e.target.value)} />
              </FormField>
            </div>
          </details>

          <StructuredAddressFieldset value={structuredAddress} onChange={setStructuredAddress} fieldErr={fieldErr} />

          <WarningsBanner warnings={error ? [error] : []} variant="error" />
          <button className="primary" type="submit" style={{ marginTop: "0.75rem" }} disabled={checkingDuplicate}>
            {checkingDuplicate ? t("checking") : editing ? t("saveChanges") : t("add")}
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

      <DataTable<SupplierParty>
        endpoint="/parties/suppliers/"
        refreshToken={refreshToken}
        onEdit={startEdit}
        columns={[
          { key: "code", label: t("code"), sortable: true },
          { key: "name", label: t("name"), sortable: true },
          { key: "phone", label: t("phone") },
          { key: "email", label: t("email") },
        ]}
      />
    </div>
  );
}
