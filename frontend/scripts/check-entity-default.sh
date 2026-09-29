#!/bin/sh
# Sprint 6.5.14: legal_entity_ids[0] was sorted alphabetically by UUID
# string, unrelated to entity_type — a simplified-mode tenant's own
# documents could sit split across its company/branch entities with
# nothing tying "the default" to either one consistently (the real-
# tenant evidence is in docs/prompts/sprint-6.5.md §6.5.14). Every
# call site was migrated to me.default_legal_entity_id
# (apps.organization.services.default_legal_entity_id_for_user, a
# documented, deterministic pick). This is the anti-recurrence guard:
# fails the build if the blind [0] pattern ever comes back.
set -e

echo "== check-entity-default: legal_entity_ids[0] must never reappear =="
MATCHES=$(find src \( -name '*.ts' -o -name '*.tsx' \) -type f -exec grep -n 'legal_entity_ids\[0\]' {} + || true)
if [ -n "$MATCHES" ]; then
  echo "$MATCHES"
  echo "FAIL: legal_entity_ids[0] found — use me.default_legal_entity_id instead (sprint 6.5.14)"
  exit 1
fi
echo "PASS: no legal_entity_ids[0] usage found"
