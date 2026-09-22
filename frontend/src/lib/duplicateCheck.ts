import { api } from "./api";
import type { DuplicateCheckResponse, Party } from "./types";

/** Sprint 3.5 (docs/SYSTEM_ANALYSIS.md 3.3 v1.4 item 4): the actual
 * check lives in the backend (`/api/parties/check-duplicate/`) — this
 * just calls it. Shared by every dedicated screen (Customers/Suppliers/
 * Employees/Affiliates) and the invoice quick-add modal, since they all
 * need the exact same "already registered as X — add as Y too?" flow. */
export async function checkPartyDuplicate(
  taxNumber: string,
  nationalIdOrCr: string
): Promise<Party | null> {
  if (!taxNumber && !nationalIdOrCr) return null;
  const params = new URLSearchParams();
  if (taxNumber) params.set("tax_number", taxNumber);
  if (nationalIdOrCr) params.set("national_id_or_cr", nationalIdOrCr);
  const data = await api.get<DuplicateCheckResponse>(`/parties/check-duplicate/?${params.toString()}`);
  return data.party;
}
