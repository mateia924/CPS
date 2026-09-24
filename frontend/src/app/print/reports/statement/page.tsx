"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { Money } from "@/components/Money";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import type { LegalEntity, Paginated, PartyRoleType, PartyStatement } from "@/lib/types";

const ROLE_PATH: Record<PartyRoleType, string> = {
  customer: "/parties/customers/",
  supplier: "/parties/suppliers/",
  employee: "/parties/employees/",
  affiliate: "/parties/affiliates/",
  bank: "/parties/customers/", // never reached — statement is only offered for these three roles
};

// Sprint 6.0.1-B, print style per BRAND.md §2.8 rule 5 / block 5.6: CPS
// logo, the entity letterhead, title, party, period, preparer, two
// signatures. A statement isn't tied to one legal_entity the way an
// invoice/voucher is (its account is tenant-wide) — the letterhead
// uses the tenant's first legal entity, the common case for a
// simplified-mode (single-branch) tenant.
function StatementPrint() {
  const { t } = useLocale();
  const { user } = useAuth();
  const searchParams = useSearchParams();
  const partyId = searchParams.get("party") || "";
  const role = (searchParams.get("role") as PartyRoleType) || "customer";
  const dateFrom = searchParams.get("from") || "";
  const dateTo = searchParams.get("to") || "";

  const [entity, setEntity] = useState<LegalEntity | null>(null);
  const [partyName, setPartyName] = useState("");
  const [statement, setStatement] = useState<PartyStatement | null>(null);

  useEffect(() => {
    if (!partyId) return;
    api.get<Paginated<LegalEntity>>("/legal-entities/").then((data) => setEntity(data.results[0] || null));
    api.get<{ name: string }>(`${ROLE_PATH[role]}${partyId}/`).then((p) => setPartyName(p.name));
    const params = new URLSearchParams({ role });
    if (dateFrom) params.set("from", dateFrom);
    if (dateTo) params.set("to", dateTo);
    api.get<PartyStatement>(`/parties/${partyId}/statement/?${params.toString()}`).then(setStatement);
  }, [partyId, role, dateFrom, dateTo]);

  if (!statement || !entity) return null;

  return (
    <div>
      <div className="print-actions">
        <button className="primary" onClick={() => window.print()}>
          {t("printButton")}
        </button>
      </div>
      <div className="print-page">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
          <div style={{ display: "flex", gap: "0.75rem", alignItems: "start" }}>
            <img src="/brand/cps-logo-horizontal.svg" alt="CPS" style={{ height: 48 }} />
            <div>
              <h2 style={{ margin: 0 }}>{entity.name}</h2>
            </div>
          </div>
          <div style={{ textAlign: "end" }}>
            <h2>{t("statementReportNav")}</h2>
            <p>
              {t("party")}: {partyName}
            </p>
            {(dateFrom || dateTo) && (
              <p>
                {t("dateFrom")}: {dateFrom || "—"} — {t("dateTo")}: {dateTo || "—"}
              </p>
            )}
            <p>
              {t("preparedBy")}: {user?.first_name || user?.email}
            </p>
          </div>
        </div>

        <hr style={{ margin: "1.5rem 0", border: "none", borderTop: "1px solid var(--border)" }} />

        <p>
          {t("openingBalance")}: <Money amount={statement.opening_balance} />
        </p>

        <table style={{ marginTop: "1rem" }}>
          <thead>
            <tr>
              <th>{t("date")}</th>
              <th>{t("number")}</th>
              <th>{t("description")}</th>
              <th>{t("debitFc")}</th>
              <th>{t("creditFc")}</th>
              <th>{t("runningBalance")}</th>
            </tr>
          </thead>
          <tbody>
            {statement.lines.map((line) => (
              <tr key={`${line.entry_id}-${line.date}`}>
                <td>{line.date}</td>
                <td>{line.entry_number}</td>
                <td>{line.description}</td>
                <td>{line.debit !== "0.00" ? <Money amount={line.debit} /> : ""}</td>
                <td>{line.credit !== "0.00" ? <Money amount={line.credit} /> : ""}</td>
                <td>
                  <Money amount={line.running_balance} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <p style={{ marginTop: "1rem", fontSize: "1.1rem" }}>
          <strong>
            {t("closingBalance")}: <Money amount={statement.closing_balance} />
          </strong>
        </p>

        <div className="print-signatures">
          <div>{t("signatureAccountant")}</div>
          <div>{t("signatureManager")}</div>
        </div>
      </div>
    </div>
  );
}

export default function StatementPrintPage() {
  return (
    <Suspense fallback={null}>
      <StatementPrint />
    </Suspense>
  );
}
