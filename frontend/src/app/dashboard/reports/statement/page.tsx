"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { Money } from "@/components/Money";
import { useLocale } from "@/lib/i18n";
import type { Paginated, PartyRoleType, PartyStatement } from "@/lib/types";

interface PartySearchResult {
  id: string;
  name: string;
  role: PartyRoleType;
}

// Sprint 6.0.1-B (compliance report §ج): "كشف حساب" as its own Reports
// screen with a unified party picker — GET /api/parties/{id}/statement/
// already existed (5.4/5.6, used per-record by PartyStatementCard);
// customers/suppliers/employees don't share one search endpoint (the
// only one that does, PartyViewSet, is gated by the manager-only
// `parties.view_all`), so this searches the three role-scoped screens'
// own list endpoints in parallel instead — all three already require
// only `parties.view`, matching the statement action's own permission.
const ROLE_ENDPOINTS: { role: PartyRoleType; path: string; labelKey: "roleCustomer" | "roleSupplier" | "roleEmployee" }[] = [
  { role: "customer", path: "/parties/customers/", labelKey: "roleCustomer" },
  { role: "supplier", path: "/parties/suppliers/", labelKey: "roleSupplier" },
  { role: "employee", path: "/parties/employees/", labelKey: "roleEmployee" },
];

function StatementReport() {
  const { t } = useLocale();
  const searchParams = useSearchParams();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<PartySearchResult[]>([]);
  const [partyId, setPartyId] = useState(searchParams.get("party") || "");
  const [role, setRole] = useState<PartyRoleType | "">((searchParams.get("role") as PartyRoleType) || "");
  const [partyLabel, setPartyLabel] = useState("");
  const [dateFrom, setDateFrom] = useState(searchParams.get("from") || "");
  const [dateTo, setDateTo] = useState(searchParams.get("to") || "");
  const [statement, setStatement] = useState<PartyStatement | null>(null);

  const search = async () => {
    if (!query) {
      setResults([]);
      return;
    }
    const lists = await Promise.all(
      ROLE_ENDPOINTS.map((r) =>
        api
          .get<Paginated<{ id: string; name: string }>>(`${r.path}?search=${encodeURIComponent(query)}`)
          .then((data) => data.results.map((p) => ({ id: p.id, name: p.name, role: r.role })))
      )
    );
    setResults(lists.flat());
  };

  const selectParty = (p: PartySearchResult) => {
    setPartyId(p.id);
    setRole(p.role);
    setPartyLabel(p.name);
    setResults([]);
    setQuery("");
  };

  const load = async () => {
    if (!partyId || !role) return;
    const params = new URLSearchParams();
    params.set("role", role);
    if (dateFrom) params.set("from", dateFrom);
    if (dateTo) params.set("to", dateTo);
    const data = await api.get<PartyStatement>(`/parties/${partyId}/statement/?${params.toString()}`);
    setStatement(data);
  };

  useEffect(() => {
    if (partyId && role) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [partyId, role]);

  const printHref =
    partyId && role
      ? `/print/reports/statement?party=${partyId}&role=${role}&from=${dateFrom}&to=${dateTo}`
      : null;

  return (
    <div>
      <h1>{t("statementReportNav")}</h1>

      <div className="card">
        <div className="form-field">
          <label>{t("selectParty")}</label>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <input
              value={partyId ? partyLabel : query}
              onChange={(e) => {
                setPartyId("");
                setStatement(null);
                setQuery(e.target.value);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  search();
                }
              }}
              placeholder={t("searchPartyPlaceholder")}
              style={{ minWidth: "260px" }}
            />
            <button type="button" className="secondary" onClick={search}>
              {t("search")}
            </button>
          </div>
          {results.length > 0 && (
            <div className="card" style={{ marginTop: "0.5rem", padding: "0.5rem" }}>
              <p style={{ margin: "0 0 0.3rem", fontSize: "0.8rem", color: "var(--muted)" }}>
                {t("partySearchResults")}
              </p>
              {results.map((r) => (
                <div key={`${r.role}-${r.id}`} style={{ padding: "0.2rem 0" }}>
                  <button type="button" className="secondary" onClick={() => selectParty(r)}>
                    {r.name} — {t(ROLE_ENDPOINTS.find((x) => x.role === r.role)!.labelKey)}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end" }}>
          <div className="form-field">
            <label>{t("dateFrom")}</label>
            <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          </div>
          <div className="form-field">
            <label>{t("dateTo")}</label>
            <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          </div>
          <button className="primary" onClick={load} disabled={!partyId}>
            {t("submit")}
          </button>
          {printHref && (
            <Link href={printHref} className="secondary" target="_blank">
              {t("printButton")}
            </Link>
          )}
        </div>
      </div>

      {statement && (
        <div className="card">
          <p>
            {t("openingBalance")}: <Money amount={statement.opening_balance} />
          </p>
          {statement.lines.length === 0 ? (
            <p style={{ color: "var(--muted)" }}>{t("noData")}</p>
          ) : (
            <table>
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
                    <td>
                      <Link href={`/dashboard/accounting/journal-entries/${line.entry_id}`}>
                        {line.entry_number}
                      </Link>
                    </td>
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
          )}
          <p style={{ marginTop: "0.5rem" }}>
            <strong>
              {t("closingBalance")}: <Money amount={statement.closing_balance} />
            </strong>
          </p>

          {statement.open_invoices.length > 0 && (
            <>
              <h3 style={{ marginTop: "1rem" }}>{t("openInvoices")}</h3>
              <table>
                <thead>
                  <tr>
                    <th>{t("number")}</th>
                    <th>{t("dueDate")}</th>
                    <th>{t("total")}</th>
                    <th>{t("balanceDue")}</th>
                  </tr>
                </thead>
                <tbody>
                  {statement.open_invoices.map((inv) => (
                    <tr key={inv.id}>
                      <td>{inv.number}</td>
                      <td>{inv.due_date || "—"}</td>
                      <td>
                        <Money amount={inv.total} currency={inv.currency} />
                      </td>
                      <td>
                        <Money amount={inv.balance_fc} currency={inv.currency} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export default function StatementReportPage() {
  return (
    <Suspense fallback={null}>
      <StatementReport />
    </Suspense>
  );
}
