"use client";

import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { checkPartyDuplicate } from "@/lib/duplicateCheck";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { EMPTY_STRUCTURED_ADDRESS, StructuredAddressFieldset } from "@/components/StructuredAddressFieldset";
import type { CustomerParty, StructuredAddressFields } from "@/lib/types";

const ROLE_LABEL_KEY: Record<string, string> = {
  customer: "customerRole",
  supplier: "supplierRole",
  employee: "employeeRole",
  affiliate: "affiliateRole",
  bank: "bankRole",
};

export default function CustomersPage() {
  const { t } = useLocale();
  const [editing, setEditing] = useState<CustomerParty | null>(null);
  const [name, setName] = useState("");
  const [partyType, setPartyType] = useState<"individual" | "organization">("organization");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [taxNumber, setTaxNumber] = useState("");
  const [nationalIdOrCr, setNationalIdOrCr] = useState("");
  const [defaultCurrency, setDefaultCurrency] = useState("SAR");
  const [creditLimit, setCreditLimit] = useState("");
  const [paymentTermsDays, setPaymentTermsDays] = useState("");
  const [salesRep, setSalesRep] = useState("");
  const [notes, setNotes] = useState("");
  const [structuredAddress, setStructuredAddress] = useState<StructuredAddressFields>(EMPTY_STRUCTURED_ADDRESS);
  const [error, setError] = useState<string | null>(null);
  const [checkingDuplicate, setCheckingDuplicate] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);

  const startEdit = (party: CustomerParty) => {
    setEditing(party);
    setName(party.name);
    setPartyType(party.party_type);
    setPhone(party.phone);
    setEmail(party.email);
    setTaxNumber(party.tax_number);
    setNationalIdOrCr(party.national_id_or_cr);
    setDefaultCurrency(party.default_currency);
    setCreditLimit(party.credit_limit || "");
    setPaymentTermsDays(party.payment_terms_days?.toString() || "");
    setSalesRep(party.sales_rep || "");
    setNotes(party.notes);
    setStructuredAddress({
      building_number: party.building_number, street: party.street, district: party.district,
      city: party.city, postal_code: party.postal_code, short_address: party.short_address,
    });
    setError(null);
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
    setCreditLimit("");
    setPaymentTermsDays("");
    setSalesRep("");
    setNotes("");
    setStructuredAddress(EMPTY_STRUCTURED_ADDRESS);
    setError(null);
  };

  const buildPayload = () => ({
    name,
    party_type: partyType,
    phone,
    email,
    tax_number: taxNumber,
    national_id_or_cr: nationalIdOrCr,
    default_currency: defaultCurrency,
    credit_limit: creditLimit || null,
    payment_terms_days: paymentTermsDays ? Number(paymentTermsDays) : null,
    sales_rep: salesRep,
    notes,
    ...structuredAddress,
  });

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!editing && (taxNumber || nationalIdOrCr)) {
      setCheckingDuplicate(true);
      let existing;
      try {
        existing = await checkPartyDuplicate(taxNumber, nationalIdOrCr);
      } finally {
        setCheckingDuplicate(false);
      }
      if (existing && !existing.roles.some((r) => r.role === "customer")) {
        const roleNames = existing.roles.map((r) => t(ROLE_LABEL_KEY[r.role])).join("، ");
        const confirmed = window.confirm(
          `${t("alreadyRegisteredAs")} "${existing.name}" (${roleNames}). ${t("confirmAddRoleToo")}`
        );
        if (!confirmed) return;
        await api.post(`/parties/${existing.id}/add-role/`, { role: "customer" });
        cancelEdit();
        setRefreshToken((n) => n + 1);
        return;
      }
    }

    try {
      if (editing) {
        await api.patch(`/parties/customers/${editing.id}/`, buildPayload());
      } else {
        await api.post("/parties/customers/", buildPayload());
      }
      cancelEdit();
      setRefreshToken((n) => n + 1);
    } catch {
      setError("Could not save this customer.");
    }
  };

  return (
    <div>
      <h1>{t("customers")}</h1>

      <div className="card">
        <h3>{editing ? t("edit") : t("add")}</h3>
        <form onSubmit={onSubmit}>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <div className="form-field">
              <label>{t("name")}</label>
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </div>
            <div className="form-field">
              <label>{t("partyType")}</label>
              <select value={partyType} onChange={(e) => setPartyType(e.target.value as typeof partyType)}>
                <option value="organization">{t("partyTypeOrganization")}</option>
                <option value="individual">{t("individual")}</option>
              </select>
            </div>
            <div className="form-field">
              <label>{t("phone")}</label>
              <input value={phone} onChange={(e) => setPhone(e.target.value)} />
            </div>
            <div className="form-field">
              <label>{t("email")}</label>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
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
                <label>{t("nationalIdOrCr")}</label>
                <input value={nationalIdOrCr} onChange={(e) => setNationalIdOrCr(e.target.value)} />
              </div>
              <div className="form-field">
                <label>{t("defaultCurrency")}</label>
                <input value={defaultCurrency} onChange={(e) => setDefaultCurrency(e.target.value)} maxLength={3} />
              </div>
              <div className="form-field">
                <label>{t("creditLimit")}</label>
                <input type="number" step="0.01" value={creditLimit} onChange={(e) => setCreditLimit(e.target.value)} />
              </div>
              <div className="form-field">
                <label>{t("paymentTermsDays")}</label>
                <input type="number" value={paymentTermsDays} onChange={(e) => setPaymentTermsDays(e.target.value)} />
              </div>
              <div className="form-field">
                <label>{t("salesRep")}</label>
                <input value={salesRep} onChange={(e) => setSalesRep(e.target.value)} />
              </div>
              <div className="form-field" style={{ flex: 1, minWidth: "200px" }}>
                <label>{t("notes")}</label>
                <input value={notes} onChange={(e) => setNotes(e.target.value)} />
              </div>
            </div>
          </details>

          <StructuredAddressFieldset value={structuredAddress} onChange={setStructuredAddress} />

          {error && <p className="error-text">{error}</p>}
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

      <DataTable<CustomerParty>
        endpoint="/parties/customers/"
        refreshToken={refreshToken}
        onEdit={startEdit}
        renderExtraActions={(party) => (
          <Link href={`/dashboard/customers/${party.id}`} className="secondary">
            {t("viewDetails")}
          </Link>
        )}
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
