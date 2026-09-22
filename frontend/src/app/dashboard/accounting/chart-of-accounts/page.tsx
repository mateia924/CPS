"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { DataTable } from "@/components/DataTable";
import { AccountTree } from "@/components/AccountTree";
import { flattenAccountTree } from "@/lib/accounts";
import type { Account, AccountTreeNode, AccountType } from "@/lib/types";

const TYPES: AccountType[] = ["asset", "liability", "equity", "revenue", "expense"];

export default function ChartOfAccountsPage() {
  const { t } = useLocale();
  const [view, setView] = useState<"list" | "tree">("tree");
  const [tree, setTree] = useState<AccountTreeNode[]>([]);
  const [editing, setEditing] = useState<Account | null>(null);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [type, setType] = useState<AccountType>("asset");
  const [parentId, setParentId] = useState("");
  const [normalBalance, setNormalBalance] = useState<"debit" | "credit" | "">("");
  const [allowPosting, setAllowPosting] = useState(true);
  const [isIntercompany, setIsIntercompany] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);

  const loadTree = async () => {
    const data = await api.get<AccountTreeNode[]>("/accounts/tree/");
    setTree(data);
  };

  useEffect(() => {
    loadTree();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshToken]);

  const parentOptions = flattenAccountTree(tree);

  const startAddChild = (parent: AccountTreeNode) => {
    setEditing(null);
    setCode("");
    setName("");
    setType(parent.type);
    setParentId(parent.id);
    setNormalBalance("");
    setAllowPosting(true);
    setIsIntercompany(false);
    setError(null);
  };

  const startEdit = (account: Account) => {
    setEditing(account);
    setCode(account.code);
    setName(account.name);
    setType(account.type);
    setParentId(account.parent || "");
    setNormalBalance(account.normal_balance);
    setAllowPosting(account.allow_posting);
    setIsIntercompany(account.is_intercompany);
    setError(null);
  };

  const cancelEdit = () => {
    setEditing(null);
    setCode("");
    setName("");
    setType("asset");
    setParentId("");
    setNormalBalance("");
    setAllowPosting(true);
    setIsIntercompany(false);
    setError(null);
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const payload = {
      code,
      name,
      type,
      parent: parentId || null,
      ...(normalBalance ? { normal_balance: normalBalance } : {}),
      allow_posting: allowPosting,
      is_intercompany: isIntercompany,
    };
    try {
      if (editing) {
        await api.patch(`/accounts/${editing.id}/`, payload);
      } else {
        await api.post("/accounts/", payload);
      }
      cancelEdit();
      setRefreshToken((n) => n + 1);
    } catch {
      setError("Could not save this account.");
    }
  };

  return (
    <div>
      <h1>{t("chartOfAccounts")}</h1>

      <div className="card">
        <h3>{editing ? t("edit") : t("add")}</h3>
        <form onSubmit={onSubmit}>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <div className="form-field">
              <label>{t("code")}</label>
              <input value={code} onChange={(e) => setCode(e.target.value)} required />
            </div>
            <div className="form-field">
              <label>{t("name")}</label>
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </div>
            <div className="form-field">
              <label>{t("accountType")}</label>
              <select value={type} onChange={(e) => setType(e.target.value as AccountType)} required>
                {TYPES.map((ty) => (
                  <option key={ty} value={ty}>
                    {t(`${ty}Type`)}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-field">
              <label>{t("parent")}</label>
              <select value={parentId} onChange={(e) => setParentId(e.target.value)}>
                <option value="">{t("none")}</option>
                {parentOptions.map((opt) => (
                  <option key={opt.id} value={opt.id}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <details style={{ marginTop: "0.75rem" }}>
            <summary style={{ cursor: "pointer" }}>{t("advanced")}</summary>
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
              <div className="form-field">
                <label>{t("normalBalance")}</label>
                <select value={normalBalance} onChange={(e) => setNormalBalance(e.target.value as "debit" | "credit" | "")}>
                  <option value="">{t("autoOption")}</option>
                  <option value="debit">{t("debit")}</option>
                  <option value="credit">{t("credit")}</option>
                </select>
              </div>
              <label style={{ display: "flex", alignItems: "center", gap: "0.3rem" }}>
                <input type="checkbox" checked={allowPosting} onChange={(e) => setAllowPosting(e.target.checked)} />
                {t("allowPosting")}
              </label>
              <label style={{ display: "flex", alignItems: "center", gap: "0.3rem" }}>
                <input
                  type="checkbox"
                  checked={isIntercompany}
                  onChange={(e) => setIsIntercompany(e.target.checked)}
                />
                {t("isIntercompany")}
              </label>
            </div>
          </details>

          {error && <p className="error-text">{error}</p>}
          <button className="primary" type="submit" style={{ marginTop: "0.75rem" }}>
            {editing ? t("saveChanges") : t("add")}
          </button>
          {editing && (
            <button
              type="button"
              className="secondary"
              style={{ marginTop: "0.75rem", marginInlineStart: "0.5rem" }}
              onClick={cancelEdit}
            >
              {t("cancel")}
            </button>
          )}
        </form>
      </div>

      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "0.75rem" }}>
        <button className={view === "tree" ? "primary" : "secondary"} onClick={() => setView("tree")}>
          {t("chartOfAccounts")}
        </button>
        <button className={view === "list" ? "primary" : "secondary"} onClick={() => setView("list")}>
          {t("search")}
        </button>
      </div>

      {view === "tree" ? (
        <div className="card">
          <AccountTree roots={tree} onAddChild={startAddChild} />
        </div>
      ) : (
        <DataTable<Account>
          endpoint="/accounts/"
          refreshToken={refreshToken}
          onEdit={startEdit}
          columns={[
            { key: "code", label: t("code"), sortable: true },
            { key: "name", label: t("name"), sortable: true },
            { key: "type", label: t("accountType"), render: (row) => t(`${row.type}Type`) },
            { key: "normal_balance", label: t("normalBalance"), render: (row) => t(row.normal_balance) },
          ]}
        />
      )}
    </div>
  );
}
