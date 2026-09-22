"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import type { Asset, Custody, EmployeeParty, Paginated } from "@/lib/types";

// 3.18 rule 2 — for an employee, its relations are the custodies and
// assets held in their name.
export default function EmployeeDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { t } = useLocale();
  const [employee, setEmployee] = useState<EmployeeParty | null>(null);
  const [custodies, setCustodies] = useState<Custody[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);

  useEffect(() => {
    Promise.all([
      api.get<EmployeeParty>(`/parties/employees/${id}/`),
      api.get<Paginated<Custody>>(`/custodies/?employee=${id}`),
      api.get<Paginated<Asset>>(`/assets/?custodian=${id}`),
    ]).then(([employeeData, custodyData, assetData]) => {
      setEmployee(employeeData);
      setCustodies(custodyData.results);
      setAssets(assetData.results);
    });
  }, [id]);

  if (!employee) return null;

  return (
    <div>
      <button className="secondary" onClick={() => router.push("/dashboard/employees")}>
        ← {t("back")}
      </button>

      <h1 style={{ marginTop: "1rem" }}>{employee.name}</h1>
      <p style={{ color: "var(--muted)" }}>{employee.code}</p>

      <div className="card">
        <h3>{t("employeesNav")}</h3>
        <p>{t("jobTitle")}: {employee.job_title || "—"}</p>
        <p>{t("phone")}: {employee.phone || "—"}</p>
        <p>{t("hireDate")}: {employee.hire_date || "—"}</p>
        <p>{t("directManager")}: {employee.direct_manager || "—"}</p>
      </div>

      <div className="card">
        <h3>{t("relatedCustodies")}</h3>
        {custodies.length === 0 ? (
          <p style={{ color: "var(--muted)" }}>{t("noData")}</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>{t("name")}</th>
                <th>{t("currency")}</th>
              </tr>
            </thead>
            <tbody>
              {custodies.map((custody) => (
                <tr key={custody.id}>
                  <td>{custody.name}</td>
                  <td>{custody.currency}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h3>{t("relatedAssets")}</h3>
        {assets.length === 0 ? (
          <p style={{ color: "var(--muted)" }}>{t("noData")}</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>{t("code")}</th>
                <th>{t("name")}</th>
                <th>{t("category")}</th>
              </tr>
            </thead>
            <tbody>
              {assets.map((asset) => (
                <tr key={asset.id}>
                  <td>{asset.code}</td>
                  <td>{asset.name}</td>
                  <td>{t(asset.category)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
