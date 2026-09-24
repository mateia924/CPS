"use client";

import Link from "next/link";
import { useLocale } from "@/lib/i18n";
import type { AccountTreeNode } from "@/lib/types";

function TreeNode({ node, onAddChild }: { node: AccountTreeNode; onAddChild: (parent: AccountTreeNode) => void }) {
  const { t } = useLocale();
  const hasChildren = node.children.length > 0;

  const label = (
    <span>
      <strong>{node.code}</strong> — {node.name}{" "}
      <span style={{ color: "var(--muted)" }}>
        ({t(`${node.type}Type`)}
        {!node.is_active ? `, ${t("inactive")}` : ""})
      </span>{" "}
      {!node.allow_manual_posting && (
        <span
          style={{
            display: "inline-block", padding: "0.05rem 0.5rem", borderRadius: "var(--radius-pill)",
            fontSize: "0.7rem", color: "var(--color-on-primary)", background: "var(--danger)",
          }}
        >
          {t("controlAccountBadge")}
        </span>
      )}{" "}
      <span style={{ color: "var(--muted)" }}>{node.balance}</span>{" "}
      {!hasChildren && (
        <Link
          href={`/dashboard/reports/ledger?account=${node.id}`}
          className="secondary"
          style={{ fontSize: "0.75rem", padding: "0.1rem 0.5rem", display: "inline-block" }}
        >
          {t("movementsTab")}
        </Link>
      )}{" "}
      <button
        type="button"
        className="secondary"
        style={{ fontSize: "0.75rem", padding: "0.1rem 0.5rem" }}
        onClick={() => onAddChild(node)}
      >
        {t("addChild")}
      </button>
    </span>
  );

  if (!hasChildren) {
    return <li style={{ listStyle: "none", padding: "0.25rem 0" }}>{label}</li>;
  }

  return (
    <li style={{ listStyle: "none", padding: "0.25rem 0" }}>
      <details open>
        <summary style={{ cursor: "pointer" }}>{label}</summary>
        <ul style={{ marginInlineStart: "1.25rem", padding: 0 }}>
          {node.children.map((child) => (
            <TreeNode key={child.id} node={child} onAddChild={onAddChild} />
          ))}
        </ul>
      </details>
    </li>
  );
}

export function AccountTree({
  roots,
  onAddChild,
}: {
  roots: AccountTreeNode[];
  onAddChild: (parent: AccountTreeNode) => void;
}) {
  return (
    <ul style={{ padding: 0 }}>
      {roots.map((root) => (
        <TreeNode key={root.id} node={root} onAddChild={onAddChild} />
      ))}
    </ul>
  );
}
