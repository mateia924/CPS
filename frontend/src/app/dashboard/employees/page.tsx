"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { checkPartyDuplicate } from "@/lib/duplicateCheck";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import type { EmployeeParty, LegalEntity, Paginated } from "@/lib/types";

const ROLE_LABEL_KEY: Record<string, string> = {
  customer: "customerRole",
  supplier: "supplierRole",
  employee: "employeeRole",
  affiliate: "affiliateRole",
  bank: "bankRole",
};

export default function EmployeesPage() {
  const { t } = useLocale();
  const { me } = useAuth();
  const [entities, setEntities] = useState<LegalEntity[]>([]);
  const [editing, setEditing] = useState<EmployeeParty | null>(null);
  const [name, setName] = useState("");
  const [nationalIdOrCr, setNationalIdOrCr] = useState("");
  const [jobTitle, setJobTitle] = useState("");
  const [phone, setPhone] = useState("");
  const [hireDate, setHireDate] = useState("");
  const [directManager, setDirectManager] = useState("");
  const [branchId, setBranchId] = useState("");
  const [salaryCurrency, setSalaryCurrency] = useState("SAR");
  const [createLinkedCostCenter, setCreateLinkedCostCenter] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checkingDuplicate, setCheckingDuplicate] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);

  // 3.13: a single-branch tenant never needs to pick a branch at all —
  // same simplified-mode gate already used for the invoice legal_entity
  // picker.
  const needsBranchPicker = !!me && !me.simplified_mode;

  useEffect(() => {
    if (needsBranchPicker) {
      api.get<Paginated<LegalEntity>>("/legal-entities/").then((data) => setEntities(data.results));
    }
  }, [needsBranchPicker]);

  const startEdit = (party: EmployeeParty) => {
    setEditing(party);
    setName(party.name);
    setNationalIdOrCr(party.national_id_or_cr);
    setJobTitle(party.job_title || "");
    setPhone(party.phone);
    setHireDate(party.hire_date || "");
    setDirectManager(party.direct_manager || "");
    setBranchId(party.branch || "");
    setSalaryCurrency(party.salary_currency || "SAR");
    setError(null);
  };

  const cancelEdit = () => {
    setEditing(null);
    setName("");
    setNationalIdOrCr("");
    setJobTitle("");
    setPhone("");
    setHireDate("");
    setDirectManager("");
    setBranchId("");
    setSalaryCurrency("SAR");
    setCreateLinkedCostCenter(false);
    setError(null);
  };

  const buildPayload = () => ({
    name,
    national_id_or_cr: nationalIdOrCr,
    job_title: jobTitle,
    phone,
    hire_date: hireDate || null,
    direct_manager: directManager,
    branch: branchId || null,
    salary_currency: salaryCurrency,
    ...(editing ? {} : { create_linked_cost_center: createLinkedCostCenter }),
  });

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!editing && nationalIdOrCr) {
      setCheckingDuplicate(true);
      let existing;
      try {
        existing = await checkPartyDuplicate("", nationalIdOrCr);
      } finally {
        setCheckingDuplicate(false);
      }
      if (existing && !existing.roles.some((r) => r.role === "employee")) {
        const roleNames = existing.roles.map((r) => t(ROLE_LABEL_KEY[r.role])).join("، ");
        const confirmed = window.confirm(
          `${t("alreadyRegisteredAs")} "${existing.name}" (${roleNames}). ${t("confirmAddRoleToo")}`
        );
        if (!confirmed) return;
        await api.post(`/parties/${existing.id}/add-role/`, { role: "employee" });
        cancelEdit();
        setRefreshToken((n) => n + 1);
        return;
      }
    }

    try {
      if (editing) {
        await api.patch(`/parties/employees/${editing.id}/`, buildPayload());
      } else {
        await api.post("/parties/employees/", buildPayload());
      }
      cancelEdit();
      setRefreshToken((n) => n + 1);
    } catch {
      setError("Could not save this employee.");
    }
  };

  return (
    <div>
      <h1>{t("employeesNav")}</h1>

      <div className="card">
        <h3>{editing ? t("edit") : t("add")}</h3>
        <form onSubmit={onSubmit}>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <div className="form-field">
              <label>{t("name")}</label>
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </div>
            <div className="form-field">
              <label>{t("employeeNationalId")}</label>
              <input value={nationalIdOrCr} onChange={(e) => setNationalIdOrCr(e.target.value)} />
            </div>
            <div className="form-field">
              <label>{t("jobTitle")}</label>
              <input value={jobTitle} onChange={(e) => setJobTitle(e.target.value)} />
            </div>
            <div className="form-field">
              <label>{t("phone")}</label>
              <input value={phone} onChange={(e) => setPhone(e.target.value)} />
            </div>
            {needsBranchPicker && (
              <div className="form-field">
                <label>{t("branch")}</label>
                <select value={branchId} onChange={(e) => setBranchId(e.target.value)}>
                  <option value="">{t("none")}</option>
                  {entities.map((entity) => (
                    <option key={entity.id} value={entity.id}>
                      {entity.code} — {entity.name}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          {!editing && (
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
                <label>{t("hireDate")}</label>
                <input type="date" value={hireDate} onChange={(e) => setHireDate(e.target.value)} />
              </div>
              <div className="form-field">
                <label>{t("directManager")}</label>
                <input value={directManager} onChange={(e) => setDirectManager(e.target.value)} />
              </div>
              <div className="form-field">
                <label>{t("salaryCurrency")}</label>
                <input value={salaryCurrency} onChange={(e) => setSalaryCurrency(e.target.value)} maxLength={3} />
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

      <DataTable<EmployeeParty>
        endpoint="/parties/employees/"
        refreshToken={refreshToken}
        onEdit={startEdit}
        renderExtraActions={(party) => (
          <Link href={`/dashboard/employees/${party.id}`} className="secondary">
            {t("viewDetails")}
          </Link>
        )}
        columns={[
          { key: "code", label: t("code"), sortable: true },
          { key: "name", label: t("name"), sortable: true },
          { key: "job_title", label: t("jobTitle") },
          { key: "phone", label: t("phone") },
        ]}
      />
    </div>
  );
}
