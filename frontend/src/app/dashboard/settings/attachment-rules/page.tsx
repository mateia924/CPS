"use client";

import { useState } from "react";
import { api, generalError } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { CATEGORY_LABEL_KEY } from "@/components/AttachmentPanel";
import type { AttachmentCategory, AttachmentRule, AttachmentRuleDocType } from "@/lib/types";

const DOC_TYPES: AttachmentRuleDocType[] = [
  "invoice", "journal_entry", "voucher_payment", "voucher_receipt", "voucher_settlement", "opening_balance",
];
const DOC_TYPE_LABEL: Record<AttachmentRuleDocType, string> = {
  invoice: "invoiceDocType",
  journal_entry: "journalEntryDocType",
  voucher_payment: "voucherPaymentDocType",
  voucher_receipt: "voucherReceiptDocType",
  voucher_settlement: "voucherSettlementDocType",
  opening_balance: "openingBalanceDocType",
};
const CATEGORIES = Object.keys(CATEGORY_LABEL_KEY) as AttachmentCategory[];

export default function AttachmentRulesPage() {
  const { t } = useLocale();
  const [editing, setEditing] = useState<AttachmentRule | null>(null);
  const [docType, setDocType] = useState<AttachmentRuleDocType>("invoice");
  const [minAmount, setMinAmount] = useState("0");
  const [requiredCategory, setRequiredCategory] = useState<AttachmentCategory>("fatura_original");
  const [error, setError] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);

  const startEdit = (rule: AttachmentRule) => {
    setEditing(rule);
    setDocType(rule.doc_type);
    setMinAmount(rule.min_amount_base);
    setRequiredCategory(rule.required_category);
    setError(null);
  };

  const cancelEdit = () => {
    setEditing(null);
    setDocType("invoice");
    setMinAmount("0");
    setRequiredCategory("fatura_original");
    setError(null);
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const payload = { doc_type: docType, min_amount_base: minAmount, required_category: requiredCategory };
    try {
      if (editing) {
        await api.patch(`/attachment-rules/${editing.id}/`, payload);
      } else {
        await api.post("/attachment-rules/", payload);
      }
      cancelEdit();
      setRefreshToken((n) => n + 1);
    } catch (err) {
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  return (
    <div>
      <h1>{t("attachmentRulesNav")}</h1>

      <div className="card">
        <h3>{editing ? t("edit") : t("add")}</h3>
        <form onSubmit={onSubmit}>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <div className="form-field">
              <label>{t("docType")}</label>
              <select value={docType} onChange={(e) => setDocType(e.target.value as AttachmentRuleDocType)}>
                {DOC_TYPES.map((d) => (
                  <option key={d} value={d}>{t(DOC_TYPE_LABEL[d])}</option>
                ))}
              </select>
            </div>
            <div className="form-field">
              <label>{t("minAmount")}</label>
              <input type="number" step="0.01" value={minAmount} onChange={(e) => setMinAmount(e.target.value)} required />
            </div>
            <div className="form-field">
              <label>{t("requiredCategory")}</label>
              <select value={requiredCategory} onChange={(e) => setRequiredCategory(e.target.value as AttachmentCategory)}>
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>{t(CATEGORY_LABEL_KEY[c])}</option>
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
              type="button" className="secondary"
              style={{ marginTop: "0.75rem", marginInlineStart: "0.5rem" }}
              onClick={cancelEdit}
            >
              {t("cancel")}
            </button>
          )}
        </form>
      </div>

      <DataTable<AttachmentRule>
        endpoint="/attachment-rules/"
        refreshToken={refreshToken}
        onEdit={startEdit}
        hasActiveToggle={false}
        columns={[
          { key: "doc_type", label: t("docType"), render: (row) => t(DOC_TYPE_LABEL[row.doc_type]) },
          { key: "min_amount_base", label: t("minAmount"), sortable: true },
          { key: "required_category", label: t("requiredCategory"), render: (row) => t(CATEGORY_LABEL_KEY[row.required_category]) },
        ]}
      />
    </div>
  );
}
