"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import type { ApprovalDocType, ApprovalRule, Paginated, Role } from "@/lib/types";

const DOC_TYPES: ApprovalDocType[] = [
  "journal_entry", "invoice", "voucher_receipt", "voucher_payment", "voucher_settlement",
];
// iban_change/opening_balance are deliberately absent from DOC_TYPES
// (below) — both are fixed, non-deletable system rules (approvals/
// migrations/0005, 0007) that never appear in the "create a new rule"
// picker, but an existing rule row for either can still be listed, so
// the label map itself must cover the full ApprovalDocType union.
const DOC_TYPE_LABEL: Record<ApprovalDocType, string> = {
  journal_entry: "journalEntryDocType",
  invoice: "invoiceDocType",
  voucher_receipt: "voucherReceiptDocType",
  voucher_payment: "voucherPaymentDocType",
  voucher_settlement: "voucherSettlementDocType",
  iban_change: "ibanChangeDocType",
  opening_balance: "openingBalanceDocType",
};

export default function ApprovalRulesPage() {
  const { t } = useLocale();
  const [roles, setRoles] = useState<Role[]>([]);
  const [editing, setEditing] = useState<ApprovalRule | null>(null);
  const [docType, setDocType] = useState<ApprovalDocType>("journal_entry");
  const [minAmount, setMinAmount] = useState("0");
  const [requiredRoleId, setRequiredRoleId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);

  useEffect(() => {
    api.get<Paginated<Role>>("/roles/").then((data) => setRoles(data.results));
  }, []);

  const startEdit = (rule: ApprovalRule) => {
    setEditing(rule);
    setDocType(rule.doc_type);
    setMinAmount(rule.min_amount);
    setRequiredRoleId(rule.required_role);
    setError(null);
  };

  const cancelEdit = () => {
    setEditing(null);
    setDocType("journal_entry");
    setMinAmount("0");
    setRequiredRoleId("");
    setError(null);
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const payload = { doc_type: docType, min_amount: minAmount, required_role: requiredRoleId };
    try {
      if (editing) {
        await api.patch(`/approval-rules/${editing.id}/`, payload);
      } else {
        await api.post("/approval-rules/", payload);
      }
      cancelEdit();
      setRefreshToken((n) => n + 1);
    } catch {
      setError("Could not save this approval rule.");
    }
  };

  return (
    <div>
      <h1>{t("approvalRulesNav")}</h1>

      <div className="card">
        <h3>{editing ? t("edit") : t("add")}</h3>
        <form onSubmit={onSubmit}>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <div className="form-field">
              <label>{t("docType")}</label>
              <select value={docType} onChange={(e) => setDocType(e.target.value as ApprovalDocType)}>
                {DOC_TYPES.map((d) => (
                  <option key={d} value={d}>
                    {t(DOC_TYPE_LABEL[d])}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-field">
              <label>{t("minAmount")}</label>
              <input type="number" step="0.01" value={minAmount} onChange={(e) => setMinAmount(e.target.value)} required />
            </div>
            <div className="form-field">
              <label>{t("requiredRole")}</label>
              <select value={requiredRoleId} onChange={(e) => setRequiredRoleId(e.target.value)} required>
                <option value="" disabled>
                  —
                </option>
                {roles.map((role) => (
                  <option key={role.id} value={role.id}>
                    {role.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
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

      <DataTable<ApprovalRule>
        endpoint="/approval-rules/"
        refreshToken={refreshToken}
        onEdit={startEdit}
        columns={[
          { key: "doc_type", label: t("docType"), render: (row) => t(DOC_TYPE_LABEL[row.doc_type]) },
          { key: "min_amount", label: t("minAmount"), sortable: true },
        ]}
      />
    </div>
  );
}
