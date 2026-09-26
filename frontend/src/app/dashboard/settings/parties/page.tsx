"use client";

import { useState } from "react";
import { api, fieldErrors, generalError } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { WarningsBanner } from "@/components/WarningsBanner";
import { EMPTY_STRUCTURED_ADDRESS, StructuredAddressFieldset } from "@/components/StructuredAddressFieldset";
import type { Party, PartyRoleType, StructuredAddressFields } from "@/lib/types";

const ROLES: PartyRoleType[] = ["customer", "supplier", "employee", "affiliate", "bank"];
const ROLE_LABEL_KEY: Record<PartyRoleType, string> = {
  customer: "customerRole",
  supplier: "supplierRole",
  employee: "employeeRole",
  affiliate: "affiliateRole",
  bank: "bankRole",
};

export default function PartiesPage() {
  const { t } = useLocale();
  const [activeTab, setActiveTab] = useState<PartyRoleType | "">("");

  const [editing, setEditing] = useState<Party | null>(null);
  const [name, setName] = useState("");
  const [nameEn, setNameEn] = useState("");
  const [partyType, setPartyType] = useState<"individual" | "organization">("organization");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [taxNumber, setTaxNumber] = useState("");
  const [nationalIdOrCr, setNationalIdOrCr] = useState("");
  const [defaultCurrency, setDefaultCurrency] = useState("SAR");
  const [notes, setNotes] = useState("");
  const [role, setRole] = useState<PartyRoleType>("customer");
  const [createLinkedCostCenter, setCreateLinkedCostCenter] = useState(false);
  const [structuredAddress, setStructuredAddress] = useState<StructuredAddressFields>(EMPTY_STRUCTURED_ADDRESS);
  const [error, setError] = useState<string | null>(null);
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});
  const [refreshToken, setRefreshToken] = useState(0);

  const [addingRoleTo, setAddingRoleTo] = useState<Party | null>(null);
  const [newRole, setNewRole] = useState<PartyRoleType>("supplier");
  const [addRoleError, setAddRoleError] = useState<string | null>(null);

  const startEdit = (party: Party) => {
    setEditing(party);
    setName(party.name);
    setNameEn(party.name_en);
    setPartyType(party.party_type);
    setPhone(party.phone);
    setEmail(party.email);
    setTaxNumber(party.tax_number);
    setNationalIdOrCr(party.national_id_or_cr);
    setDefaultCurrency(party.default_currency);
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
    setNameEn("");
    setPartyType("organization");
    setPhone("");
    setEmail("");
    setTaxNumber("");
    setNationalIdOrCr("");
    setDefaultCurrency("SAR");
    setNotes("");
    setRole("customer");
    setCreateLinkedCostCenter(false);
    setStructuredAddress(EMPTY_STRUCTURED_ADDRESS);
    setError(null);
    setFieldErr({});
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setFieldErr({});
    const basePayload = {
      name,
      name_en: nameEn,
      party_type: partyType,
      phone,
      email,
      tax_number: taxNumber,
      national_id_or_cr: nationalIdOrCr,
      default_currency: defaultCurrency,
      notes,
      ...structuredAddress,
    };
    try {
      if (editing) {
        await api.patch(`/parties/${editing.id}/`, basePayload);
      } else {
        await api.post("/parties/", {
          ...basePayload,
          role,
          role_create_linked_cost_center: role === "employee" ? createLinkedCostCenter : undefined,
        });
      }
      cancelEdit();
      setRefreshToken((n) => n + 1);
    } catch (err) {
      setFieldErr(fieldErrors((err as { body?: unknown }).body));
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const onAddRole = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!addingRoleTo) return;
    setAddRoleError(null);
    try {
      await api.post(`/parties/${addingRoleTo.id}/add-role/`, { role: newRole });
      setAddingRoleTo(null);
      setRefreshToken((n) => n + 1);
    } catch (err) {
      setAddRoleError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  return (
    <div>
      <h1>{t("fullPartiesView")}</h1>

      <div className="card">
        <h3>{editing ? t("edit") : t("add")}</h3>
        <form onSubmit={onSubmit}>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <FormField name="name" label={t("name")} required error={fieldErr.name}>
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </FormField>
            <FormField name="party_type" label={t("partyType")} error={fieldErr.party_type}>
              <select value={partyType} onChange={(e) => setPartyType(e.target.value as typeof partyType)}>
                <option value="organization">{t("partyTypeOrganization")}</option>
                <option value="individual">{t("individual")}</option>
              </select>
            </FormField>
            <FormField name="phone" label={t("phone")} error={fieldErr.phone}>
              <input value={phone} onChange={(e) => setPhone(e.target.value)} />
            </FormField>
            {!editing && (
              <FormField name="role" label={t("roles")} error={fieldErr.role}>
                <select value={role} onChange={(e) => setRole(e.target.value as PartyRoleType)}>
                  {ROLES.map((r) => (
                    <option key={r} value={r}>
                      {t(ROLE_LABEL_KEY[r])}
                    </option>
                  ))}
                </select>
              </FormField>
            )}
          </div>

          {!editing && role === "employee" && (
            <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", marginTop: "0.5rem" }}>
              <input type="checkbox" checked={createLinkedCostCenter} onChange={(e) => setCreateLinkedCostCenter(e.target.checked)} /* form-ok: مربع اختيار إجراء إضافي، لا يُرجع خطأ حقل من الـAPI */ />
              {t("createLinkedCostCenter")}
            </label>
          )}

          <details style={{ marginTop: "0.75rem" }}>
            <summary style={{ cursor: "pointer" }}>{t("advanced")}</summary>
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
              <FormField name="name_en" label={t("nameEnglish")} error={fieldErr.name_en}>
                <input value={nameEn} onChange={(e) => setNameEn(e.target.value)} />
              </FormField>
              <FormField name="email" label={t("email")} error={fieldErr.email}>
                <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
              </FormField>
              <FormField name="tax_number" label={t("taxNumber")} error={fieldErr.tax_number}>
                <input value={taxNumber} onChange={(e) => setTaxNumber(e.target.value)} />
              </FormField>
              <FormField name="national_id_or_cr" label={t("nationalIdOrCr")} error={fieldErr.national_id_or_cr}>
                <input value={nationalIdOrCr} onChange={(e) => setNationalIdOrCr(e.target.value)} />
              </FormField>
              <FormField name="default_currency" label={t("defaultCurrency")} error={fieldErr.default_currency}>
                <input
                  value={defaultCurrency}
                  onChange={(e) => setDefaultCurrency(e.target.value)}
                  maxLength={3}
                />
              </FormField>
              <FormField name="notes" label={t("notes")} error={fieldErr.notes} style={{ flex: 1, minWidth: "200px" }}>
                <input value={notes} onChange={(e) => setNotes(e.target.value)} />
              </FormField>
            </div>
          </details>

          <StructuredAddressFieldset value={structuredAddress} onChange={setStructuredAddress} />

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

      {addingRoleTo && (
        <div className="card">
          <h3>
            {t("addRole")} — {addingRoleTo.name}
          </h3>
          <form onSubmit={onAddRole}>
            <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
              <FormField name="role" label={t("roles")}>
                <select value={newRole} onChange={(e) => setNewRole(e.target.value as PartyRoleType)}>
                  {ROLES.map((r) => (
                    <option key={r} value={r}>
                      {t(ROLE_LABEL_KEY[r])}
                    </option>
                  ))}
                </select>
              </FormField>
              <button className="primary" type="submit">
                {t("save")}
              </button>
              <button type="button" className="secondary" onClick={() => setAddingRoleTo(null)}>
                {t("cancel")}
              </button>
            </div>
            <WarningsBanner warnings={addRoleError ? [addRoleError] : []} variant="error" />
          </form>
        </div>
      )}

      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem", flexWrap: "wrap" }}>
        {(["", ...ROLES] as (PartyRoleType | "")[]).map((r) => (
          <button
            key={r || "all"}
            className={r === activeTab ? "primary" : "secondary"}
            onClick={() => setActiveTab(r)}
          >
            {r === "" ? t("all") : t(ROLE_LABEL_KEY[r])}
          </button>
        ))}
      </div>

      <DataTable<Party>
        endpoint="/parties/"
        refreshToken={refreshToken}
        extraParams={{ role: activeTab }}
        onEdit={startEdit}
        renderExtraActions={(party) => (
          <button className="secondary" onClick={() => setAddingRoleTo(party)}>
            {t("addRole")}
          </button>
        )}
        columns={[
          { key: "code", label: t("code"), sortable: true },
          { key: "name", label: t("name"), sortable: true },
          { key: "phone", label: t("phone") },
          {
            key: "roles",
            label: t("roles"),
            render: (row) => row.roles.map((r) => t(ROLE_LABEL_KEY[r.role])).join(", "),
          },
        ]}
      />
    </div>
  );
}
