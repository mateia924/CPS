"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import type { DocumentNumberingSetting, Paginated } from "@/lib/types";

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
      setError("Could not save this numbering setting.");
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
              <td>{row.doc_type}</td>
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
