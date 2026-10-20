"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { Money } from "@/components/Money";
import { formatDate } from "@/lib/date";
import type { ExpenseRow, SupplierBillFormOptions } from "@/lib/types";

/** Sprint 8.1: «المصروفات» — every posted expense line in one list, from
 * supplier bills (EXPENSE lines) and from payment vouchers' direct-account
 * lines on an expense account (5.3's direct expense item, which stays on
 * the voucher screen). Voucher rows appear only for a user who may see
 * vouchers; the API decides that, not this screen. The amount is what the
 * expense account was debited (non-deductible VAT included). */
export default function ExpensesPage() {
  const { t } = useLocale();
  const [options, setOptions] = useState<SupplierBillFormOptions | null>(null);
  const [legalEntityId, setLegalEntityId] = useState("");
  const [source, setSource] = useState("");
  const [accountId, setAccountId] = useState("");
  const [costCenterId, setCostCenterId] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [totalBase, setTotalBase] = useState<string | null>(null);

  useEffect(() => {
    api.get<SupplierBillFormOptions>("/purchasing/bills/form-options/").then(setOptions);
  }, []);

  const params = {
    legal_entity: legalEntityId, source, account: accountId, cost_center: costCenterId,
    date_from: dateFrom, date_to: dateTo,
  };

  useEffect(() => {
    const query = new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][]);
    api.get<{ total_base: string }>(`/purchasing/expenses/?${query.toString()}`).then((d) => setTotalBase(d.total_base));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [legalEntityId, source, accountId, costCenterId, dateFrom, dateTo]);

  return (
    <div>
      <h1>{t("expensesTitle")}</h1>
      <p style={{ color: "var(--muted)" }}>{t("expensesHint")}</p>

      <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
        <FormField name="list_entity_filter" label={t("entityFilter")}>
          <select value={legalEntityId} onChange={(e) => setLegalEntityId(e.target.value)}>
            <option value="">{t("allEntities")}</option>
            {options?.legal_entities.map((entity) => (
              <option key={entity.id} value={entity.id}>{entity.code} — {entity.name}</option>
            ))}
          </select>
        </FormField>
        <FormField name="source_filter" label={t("expensesSource")}>
          <select value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="">{t("expensesAllSources")}</option>
            <option value="supplier_bill">{t("expensesSourceBill")}</option>
            <option value="voucher">{t("expensesSourceVoucher")}</option>
          </select>
        </FormField>
        <FormField name="account_filter" label={t("account")}>
          <select value={accountId} onChange={(e) => setAccountId(e.target.value)}>
            <option value="">—</option>
            {options?.accounts.filter((a) => a.type === "expense").map((a) => (
              <option key={a.id} value={a.id}>{a.code} — {a.name}</option>
            ))}
          </select>
        </FormField>
        {options && options.cost_centers.length > 0 && (
          <FormField name="cost_center_filter" label={t("costCenter")}>
            <select value={costCenterId} onChange={(e) => setCostCenterId(e.target.value)}>
              <option value="">—</option>
              {options.cost_centers.map((c) => (
                <option key={c.id} value={c.id}>{c.code} — {c.name}</option>
              ))}
            </select>
          </FormField>
        )}
        <FormField name="date_from" label={t("dateFrom")}>
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </FormField>
        <FormField name="date_to" label={t("dateTo")}>
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </FormField>
      </div>

      <p data-testid="expenses-total">
        {t("expensesTotalBase")}: <Money amount={totalBase} />
      </p>

      <DataTable<ExpenseRow>
        endpoint="/purchasing/expenses/"
        extraParams={params}
        hasActiveToggle={false}
        columns={[
          { key: "date", label: t("date"), render: (row) => formatDate(row.date, "form") },
          {
            key: "source", label: t("expensesSource"),
            render: (row) => t(row.source === "supplier_bill" ? "expensesSourceBill" : "expensesSourceVoucher"),
          },
          {
            key: "number", label: t("number"),
            render: (row) => {
              const href = row.source === "supplier_bill"
                ? `/dashboard/purchasing/bills/${row.document_id}`
                : `/dashboard/treasury/vouchers/${row.document_id}`;
              return <Link href={href}>{row.number}</Link>;
            },
          },
          { key: "party_name", label: t("expensesParty") },
          { key: "account_code", label: t("account"), render: (row) => `${row.account_code} — ${row.account_name}` },
          { key: "cost_center_name", label: t("costCenter"), render: (row) => row.cost_center_name || "—" },
          { key: "description", label: t("description"), render: (row) => row.description || "—" },
          { key: "amount", label: t("billTotal"), render: (row) => <Money amount={row.amount} currency={row.currency} /> },
          { key: "amount_base", label: t("expensesTotalBase"), render: (row) => <Money amount={row.amount_base} /> },
        ]}
      />
    </div>
  );
}
