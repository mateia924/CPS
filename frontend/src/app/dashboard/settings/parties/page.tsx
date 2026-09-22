"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import type { Party, PartyRoleType } from "@/lib/types";

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
  const [error, setError] = useState<string | null>(null);
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
    setError(null);
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
    setError(null);
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
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
    } catch {
      setError("Could not save this party.");
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
    } catch {
      setAddRoleError("Could not add this role — the party may already hold it.");
    }
  };

  return (
    <div>
      <h1>{t("fullPartiesView")}</h1>

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
            {!editing && (
              <div className="form-field">
                <label>{t("roles")}</label>
                <select value={role} onChange={(e) => setRole(e.target.value as PartyRoleType)}>
                  {ROLES.map((r) => (
                    <option key={r} value={r}>
                      {t(ROLE_LABEL_KEY[r])}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          {!editing && role === "employee" && (
            <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", marginTop: "0.5rem" }}>
              <input
                type="checkbox"
                checked={createLinkedCostCenter}
                onChange={(e) => setCreateLinkedCostCenter(e.target.checked)}
              />
              {t("createLinkedCostCenter")}
            </label>
          )}

          <details style={{ marginTop: "0.75rem" }}>
            <summary style={{ cursor: "pointer" }}>{t("advanced")}</summary>
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
              <div className="form-field">
                <label>{t("nameEnglish")}</label>
                <input value={nameEn} onChange={(e) => setNameEn(e.target.value)} />
              </div>
              <div className="form-field">
                <label>{t("email")}</label>
                <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
              </div>
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
                <input
                  value={defaultCurrency}
                  onChange={(e) => setDefaultCurrency(e.target.value)}
                  maxLength={3}
                />
              </div>
              <div className="form-field" style={{ flex: 1, minWidth: "200px" }}>
                <label>{t("notes")}</label>
                <input value={notes} onChange={(e) => setNotes(e.target.value)} />
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

      {addingRoleTo && (
        <div className="card">
          <h3>
            {t("addRole")} — {addingRoleTo.name}
          </h3>
          <form onSubmit={onAddRole}>
            <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
              <select value={newRole} onChange={(e) => setNewRole(e.target.value as PartyRoleType)}>
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {t(ROLE_LABEL_KEY[r])}
                  </option>
                ))}
              </select>
              <button className="primary" type="submit">
                {t("save")}
              </button>
              <button type="button" className="secondary" onClick={() => setAddingRoleTo(null)}>
                {t("cancel")}
              </button>
            </div>
            {addRoleError && <p className="error-text">{addRoleError}</p>}
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
