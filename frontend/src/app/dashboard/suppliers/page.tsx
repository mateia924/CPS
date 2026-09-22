"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { checkPartyDuplicate } from "@/lib/duplicateCheck";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import type { SupplierParty } from "@/lib/types";

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
  const [error, setError] = useState<string | null>(null);
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
    setPaymentTermsDays("");
    setIban("");
    setNotes("");
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
    payment_terms_days: paymentTermsDays ? Number(paymentTermsDays) : null,
    iban,
    notes,
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
    } catch {
      setError("Could not save this supplier.");
    }
  };

  return (
    <div>
      <h1>{t("suppliers")}</h1>

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
                <label>{t("paymentTermsDays")}</label>
                <input type="number" value={paymentTermsDays} onChange={(e) => setPaymentTermsDays(e.target.value)} />
              </div>
              <div className="form-field">
                <label>IBAN</label>
                <input value={iban} onChange={(e) => setIban(e.target.value)} />
              </div>
              <div className="form-field" style={{ flex: 1, minWidth: "200px" }}>
                <label>{t("notes")}</label>
                <input value={notes} onChange={(e) => setNotes(e.target.value)} />
              </div>
            </div>
          </details>

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
