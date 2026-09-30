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

// Sprint 6.5.18 (UAT item 9): a disposal's own proceeds can only ever
// be received into treasury (CASH/BANKS/CUSTODIES) or booked against
// receivables (CUSTOMERS, "الذمم") — a leaf account never carries its
// own system_key (only the root of its subtree does, e.g. "1100" for
// every individual cash box created under it), so this walks down
// remembering whether the nearest tagged ancestor is one of those four.
const PROCEEDS_ACCOUNT_ROOTS = new Set(["CASH", "BANKS", "CUSTODIES", "CUSTOMERS"]);

export function flattenProceedsAccounts(nodes: AccountTreeNode[], underAllowedRoot = false): FlatAccountOption[] {
  const out: FlatAccountOption[] = [];
  for (const node of nodes) {
    const included = underAllowedRoot || PROCEEDS_ACCOUNT_ROOTS.has(node.system_key);
    if (node.children.length === 0) {
      if (included) out.push({ id: node.id, label: `${node.code} — ${node.name}` });
    } else {
      out.push(...flattenProceedsAccounts(node.children, included));
    }
  }
  return out;
}
