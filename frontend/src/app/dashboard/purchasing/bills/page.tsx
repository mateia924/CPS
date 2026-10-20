"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { Money } from "@/components/Money";
import { StatusBadge } from "@/components/StatusBadge";
import { SupplierBillForm } from "@/components/SupplierBillForm";
import { formatDate } from "@/lib/date";
import type { SupplierBill, SupplierBillFormOptions } from "@/lib/types";

const STATUSES = ["draft", "pending_approval", "approved", "posted", "reversed"] as const;

/** Sprint 8.1: فواتير الموردين — the new-bill form on top (for a user who
 * may create one), the list below with status / supplier / due / entity
 * filters («الكل» = every entity the user can see). Actions live on the
 * detail screen; the API enforces each of them whatever is shown. */
export default function SupplierBillsPage() {
  const { t } = useLocale();
  const { hasPermission } = useAuth();
  const router = useRouter();
  const canCreate = hasPermission("purchasing.manage");
  const [options, setOptions] = useState<SupplierBillFormOptions | null>(null);
  const [listEntityId, setListEntityId] = useState("");
  const [status, setStatus] = useState("");
  const [supplierId, setSupplierId] = useState("");
  const [dueBefore, setDueBefore] = useState("");

  useEffect(() => {
    api.get<SupplierBillFormOptions>("/purchasing/bills/form-options/").then(setOptions);
  }, []);

  return (
    <div>
      <h1>{t("supplierBills")}</h1>

      {canCreate && (
        <div className="card">
          <h3>{t("newSupplierBill")}</h3>
          <SupplierBillForm onSaved={(bill) => router.push(`/dashboard/purchasing/bills/${bill.id}`)} />
        </div>
      )}

      <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
        <FormField name="list_entity_filter" label={t("entityFilter")}>
          <select value={listEntityId} onChange={(e) => setListEntityId(e.target.value)}>
            <option value="">{t("allEntities")}</option>
            {options?.legal_entities.map((entity) => (
              <option key={entity.id} value={entity.id}>{entity.code} — {entity.name}</option>
            ))}
          </select>
        </FormField>
        <FormField name="status_filter" label={t("status")}>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("stockAllStatuses")}</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>{t(s)}</option>
            ))}
          </select>
        </FormField>
        <FormField name="supplier_filter" label={t("billSupplier")}>
          <select value={supplierId} onChange={(e) => setSupplierId(e.target.value)}>
            <option value="">{t("billAllSuppliers")}</option>
            {options?.suppliers.map((s) => (
              <option key={s.id} value={s.id}>{s.code} — {s.name}</option>
            ))}
          </select>
        </FormField>
        <FormField name="due_before" label={t("billDueBefore")}>
          <input type="date" value={dueBefore} onChange={(e) => setDueBefore(e.target.value)} />
        </FormField>
      </div>

      <DataTable<SupplierBill>
        endpoint="/purchasing/bills/"
        extraParams={{ legal_entity: listEntityId, status, supplier: supplierId, due_before: dueBefore }}
        hasActiveToggle={false}
        columns={[
          { key: "number", label: t("number"), render: (row) => row.number || `(${t("draft")})` },
          { key: "bill_number", label: t("supplierInvoiceNumber") },
          { key: "supplier_name", label: t("billSupplier") },
          { key: "date", label: t("billDate"), render: (row) => formatDate(row.date, "form") },
          { key: "due_date", label: t("dueDate"), render: (row) => (row.due_date ? formatDate(row.due_date, "form") : "—") },
          { key: "legal_entity_name", label: t("legalEntity") },
          { key: "total", label: t("billTotal"), render: (row) => <Money amount={row.total} currency={row.currency} /> },
          { key: "status", label: t("status"), render: (row) => <StatusBadge status={row.status} /> },
        ]}
        renderExtraActions={(row) => (
          <Link href={`/dashboard/purchasing/bills/${row.id}`} className="secondary">{t("details")}</Link>
        )}
      />
    </div>
  );
}
