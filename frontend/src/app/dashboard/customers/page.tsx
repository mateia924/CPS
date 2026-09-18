"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import type { Customer } from "@/lib/types";

export default function CustomersPage() {
  const { t } = useLocale();
  const [editing, setEditing] = useState<Customer | null>(null);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [refreshToken, setRefreshToken] = useState(0);

  const startEdit = (customer: Customer) => {
    setEditing(customer);
    setName(customer.name);
    setEmail(customer.email);
    setPhone(customer.phone);
  };

  const cancelEdit = () => {
    setEditing(null);
    setName("");
    setEmail("");
    setPhone("");
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (editing) {
      await api.patch(`/customers/${editing.id}/`, { name, email, phone });
    } else {
      await api.post("/customers/", { name, email, phone });
    }
    cancelEdit();
    setRefreshToken((n) => n + 1);
  };

  return (
    <div>
      <h1>{t("customers")}</h1>
      <div className="card">
        <form onSubmit={onSubmit} style={{ display: "flex", gap: "0.75rem", alignItems: "end", flexWrap: "wrap" }}>
          <div className="form-field">
            <label>{t("name")}</label>
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="form-field">
            <label>{t("email")}</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="form-field">
            <label>{t("phone")}</label>
            <input value={phone} onChange={(e) => setPhone(e.target.value)} />
          </div>
          <button className="primary" type="submit">
            {editing ? t("saveChanges") : t("add")}
          </button>
          {editing && (
            <button type="button" className="secondary" onClick={cancelEdit}>
              {t("cancel")}
            </button>
          )}
        </form>
      </div>

      <DataTable<Customer>
        endpoint="/customers/"
        refreshToken={refreshToken}
        onEdit={startEdit}
        columns={[
          { key: "name", label: t("name"), sortable: true },
          { key: "email", label: t("email") },
          { key: "phone", label: t("phone") },
        ]}
      />
    </div>
  );
}
