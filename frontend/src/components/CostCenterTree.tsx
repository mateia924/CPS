"use client";

import { useLocale } from "@/lib/i18n";
import type { CostCenterTreeNode } from "@/lib/types";

function TreeNode({ node }: { node: CostCenterTreeNode }) {
  const { t } = useLocale();
  const hasChildren = node.children.length > 0;

  const label = (
    <span>
      <strong>{node.code}</strong> — {node.name}{" "}
      <span style={{ color: "var(--muted)" }}>
        ({t(node.center_type)}
        {!node.is_active ? `, ${t("inactive")}` : ""})
      </span>
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
            <TreeNode key={child.id} node={child} />
          ))}
        </ul>
      </details>
    </li>
  );
}

export function CostCenterTree({ roots }: { roots: CostCenterTreeNode[] }) {
  return (
    <ul style={{ padding: 0 }}>
      {roots.map((root) => (
        <TreeNode key={root.id} node={root} />
      ))}
    </ul>
  );
}
