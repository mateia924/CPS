"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import type { DocumentNumberingSetting, Paginated } from "@/lib/types";

// Sprint 6.6.6 (check-arabic-ui): `row.doc_type` is a raw backend enum
// (apps.numbering.services.DEFAULT_PREFIXES's own key set) — never
// rendered directly, only through this key-to-translation-key map.
const DOC_TYPE_LABEL_KEY: Record<string, string> = {
  invoice: "invoiceDocType",
  journal_entry: "journalEntryDocType",
  voucher_receipt: "voucherReceiptDocType",
  voucher_payment: "voucherPaymentDocType",
  voucher_settlement: "voucherSettlementDocType",
  recurring_entry: "recurringEntries",
  cash_count: "cashCountDocType",
  party_customer: "partyCustomerDocType",
  party_supplier: "partySupplierDocType",
  party_employee: "partyEmployeeDocType",
  party_affiliate: "partyAffiliateDocType",
};

export default function DocumentNumberingPage() {
  const { t } = useLocale();
  const [rows, setRows] = useState<DocumentNumberingSetting[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    const data = await api.get<Paginated<DocumentNumberingSetting>>("/document-numbering-settings/");
    setRows(data.results);
  };

  useEffect(() => {
    load();
  }, []);

  const update = (id: string, patch: Partial<DocumentNumberingSetting>) => {
    setRows((prev) => prev.map((row) => (row.id === id ? { ...row, ...patch } : row)));
  };

  const save = async (row: DocumentNumberingSetting) => {
    setError(null);
    try {
      await api.patch(`/document-numbering-settings/${row.id}/`, {
        prefix: row.prefix,
        reset_yearly: row.reset_yearly,
        include_entity_code: row.include_entity_code,
      });
      load();
    } catch {
      setError(t("couldNotSaveNumberingSetting"));
    }
  };

  return (
    <div>
      <h1>{t("documentNumberingNav")}</h1>
      {error && <p className="error-text">{error}</p>}
      <table>
        <thead>
          <tr>
            <th>{t("docType")}</th>
            <th>{t("prefix")}</th>
            <th>{t("resetYearly")}</th>
            <th>{t("includeEntityCode")}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td>{t(DOC_TYPE_LABEL_KEY[row.doc_type] ?? row.doc_type)}</td>
              <td>
                <input
                  value={row.prefix}
                  onChange={(e) => update(row.id, { prefix: e.target.value })}
                  style={{ width: "90px" }}
                />
              </td>
              <td>
                <input
                  type="checkbox"
                  checked={row.reset_yearly}
                  onChange={(e) => update(row.id, { reset_yearly: e.target.checked })}
                />
              </td>
              <td>
                <select
                  value={row.include_entity_code === null ? "auto" : row.include_entity_code ? "yes" : "no"}
                  onChange={(e) =>
                    update(row.id, {
                      include_entity_code: e.target.value === "auto" ? null : e.target.value === "yes",
                    })
                  }
                >
                  <option value="auto">{t("autoOption")}</option>
                  <option value="yes">{t("yes")}</option>
                  <option value="no">{t("no")}</option>
                </select>
              </td>
              <td>
                <button className="secondary" onClick={() => save(row)}>
                  {t("save")}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
