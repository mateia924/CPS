"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import type { LegalEntity, Paginated, TaxPeriod } from "@/lib/types";

const STATUS_LABEL: Record<TaxPeriod["status"], string> = {
  open: "periodOpen",
  filed: "periodFiled",
  paid: "paid",
};

export default function TaxPeriodsPage() {
  const { t } = useLocale();
  const [entities, setEntities] = useState<LegalEntity[]>([]);
  // Sprint 6.6.1 (item 4): TaxPeriodViewSet is entity-scoped as of this
  // sprint — the list now mixes every accessible entity's periods, so
  // it needs the same optional "الكل"-default filter as every other
  // entity-scoped list (see assets/page.tsx).
  const [listEntityId, setListEntityId] = useState("");

  useEffect(() => {
    (async () => {
      const entityData = await api.get<Paginated<LegalEntity>>("/legal-entities/");
      setEntities(entityData.results.filter((entity) => entity.entity_type !== "holding"));
    })();
  }, []);

  return (
    <div>
      <h1>{t("taxPeriodsNav")}</h1>

      <FormField name="list_entity_filter" label={t("entityFilter")}>
        <select value={listEntityId} onChange={(e) => setListEntityId(e.target.value)}>
          <option value="">{t("allEntities")}</option>
          {entities.map((entity) => (
            <option key={entity.id} value={entity.id}>{entity.code} — {entity.name}</option>
          ))}
        </select>
      </FormField>

      <DataTable<TaxPeriod>
        endpoint="/tax-periods/"
        extraParams={{ legal_entity: listEntityId }}
        hasActiveToggle={false}
        columns={[
          { key: "legal_entity_name", label: t("legalEntity") },
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
