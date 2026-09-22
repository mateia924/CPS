"use client";

import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import type { TaxPeriod } from "@/lib/types";

const STATUS_LABEL: Record<TaxPeriod["status"], string> = {
  open: "periodOpen",
  filed: "periodFiled",
  paid: "paid",
};

export default function TaxPeriodsPage() {
  const { t } = useLocale();

  return (
    <div>
      <h1>{t("taxPeriodsNav")}</h1>
      <DataTable<TaxPeriod>
        endpoint="/tax-periods/"
        hasActiveToggle={false}
        columns={[
          { key: "period_type", label: t("periodType"), render: (row) => t(row.period_type) },
          { key: "start", label: t("periodStart"), sortable: true },
          { key: "end", label: t("periodEnd") },
          { key: "status", label: t("status"), render: (row) => t(STATUS_LABEL[row.status]) },
          { key: "reference", label: t("reference") },
        ]}
      />
    </div>
  );
}
