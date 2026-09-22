import type { AccountTreeNode } from "./types";

export interface FlatAccountOption {
  id: string;
  label: string;
}

/** Every node, indented by depth — for a parent picker. */
export function flattenAccountTree(nodes: AccountTreeNode[], depth = 0): FlatAccountOption[] {
  const out: FlatAccountOption[] = [];
  for (const node of nodes) {
    out.push({ id: node.id, label: `${"— ".repeat(depth)}${node.code} ${node.name}` });
    out.push(...flattenAccountTree(node.children, depth + 1));
  }
  return out;
}

/** Leaf nodes only — the postable accounts (3.4: "لا ترحيل إلا على
 * حساب فرعي") — for a journal-line/tax-code account picker. */
export function flattenLeafAccounts(nodes: AccountTreeNode[]): FlatAccountOption[] {
  const out: FlatAccountOption[] = [];
  for (const node of nodes) {
    if (node.children.length === 0) {
      out.push({ id: node.id, label: `${node.code} — ${node.name}` });
    } else {
      out.push(...flattenLeafAccounts(node.children));
    }
  }
  return out;
}
