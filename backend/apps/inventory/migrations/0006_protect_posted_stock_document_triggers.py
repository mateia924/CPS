# Sprint 7.2.6 (owner review, 2026-10-05): the block's first draft used
# a Python Model.save()/.delete() override to guard a posted
# StockDocument/StockDocumentLine — proven by test to be silently
# bypassed by QuerySet.update(), QuerySet.delete() (bulk), bulk_create()
# and bulk_update(), none of which call a model instance's own save()/
# delete(). A posted StockDocument will carry a real JournalEntry
# behind it once 7.3's engine exists — the same accounting weight
# JournalEntry/JournalLine already protect with a trigger (sprint 5.7,
# protect_posted_journal_entry) — so this is that same answer, applied
# here instead of staying a second, weaker mechanism for an equally
# weighted document. The model itself now carries no save()/delete()
# override at all.
#
# One function, branching on TG_TABLE_NAME, exactly like
# protect_posted_journal_entry serves both accounting_journalentry and
# accounting_journalline:
#   - inventory_stockdocument: BEFORE UPDATE OR DELETE — rejects any
#     write to a POSTED/REVERSED row except the single allowed
#     transition (status posted->reversed, every other column
#     unchanged).
#   - inventory_stockdocumentline: BEFORE INSERT OR UPDATE OR DELETE —
#     rejects any write whose parent document is POSTED/REVERSED. The
#     INSERT branch is deliberately one step past JournalLine's own
#     trigger (UPDATE/DELETE only) — a brand new line bulk_created onto
#     an already-posted document is exactly as real a violation as
#     modifying an existing one, and JournalLine's own gap there is
#     noted as inherited technical debt, not copied here.
#
# Known, accepted, documented gap (not closed by this migration): the
# `serials` ManyToMany's own through-table
# (inventory_stockdocumentline_serials) carries no trigger — see
# StockDocumentLine's own docstring for why this was left open.
from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION protect_posted_stock_document() RETURNS TRIGGER AS $$
BEGIN
    IF TG_TABLE_NAME = 'inventory_stockdocument' THEN
        IF TG_OP = 'DELETE' THEN
            IF OLD.status IN ('posted', 'reversed') THEN
                RAISE EXCEPTION 'Cannot delete a % stock document (id=%).', OLD.status, OLD.id;
            END IF;
            RETURN OLD;
        END IF;

        -- UPDATE
        IF OLD.status IN ('posted', 'reversed') THEN
            IF (OLD.status = 'posted' AND NEW.status = 'reversed') OR NEW.status = OLD.status THEN
                IF (NEW.tenant_id, NEW.legal_entity_id, NEW.warehouse_id, NEW.to_warehouse_id, NEW.kind,
                    NEW.number, NEW.date, NEW.party_id, NEW.account_id, NEW.reference, NEW.notes,
                    NEW.reverses_id, NEW.created_by_id, NEW.created_at)
                   IS DISTINCT FROM
                   (OLD.tenant_id, OLD.legal_entity_id, OLD.warehouse_id, OLD.to_warehouse_id, OLD.kind,
                    OLD.number, OLD.date, OLD.party_id, OLD.account_id, OLD.reference, OLD.notes,
                    OLD.reverses_id, OLD.created_by_id, OLD.created_at)
                THEN
                    RAISE EXCEPTION
                        'Cannot modify a % stock document (id=%) except to reverse it.', OLD.status, OLD.id;
                END IF;
            ELSE
                RAISE EXCEPTION 'Cannot modify a % stock document (id=%) except to reverse it.', OLD.status, OLD.id;
            END IF;
        END IF;
        RETURN NEW;
    END IF;

    -- inventory_stockdocumentline: look up the parent document's
    -- status. NEW is not a bound record on DELETE (referencing NEW.*
    -- raises "record new is not assigned yet"), so TG_OP is checked
    -- before any NEW.field access.
    DECLARE
        document_status varchar;
        line_document_id uuid;
    BEGIN
        IF TG_OP = 'DELETE' THEN
            line_document_id := OLD.document_id;
        ELSE
            line_document_id := NEW.document_id;
        END IF;
        SELECT status INTO document_status FROM inventory_stockdocument WHERE id = line_document_id;

        IF document_status IN ('posted', 'reversed') THEN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Cannot delete a line on a % stock document (document id=%).',
                    document_status, line_document_id;
            END IF;
            -- INSERT or UPDATE: no field may differ from a fresh row
            -- for INSERT (OLD doesn't exist), and nothing at all may
            -- change for UPDATE — a line carries no reconciliation-
            -- style carve-out the way JournalLine does.
            IF TG_OP = 'INSERT' THEN
                RAISE EXCEPTION 'Cannot add a line to a % stock document (document id=%).',
                    document_status, line_document_id;
            END IF;
            IF (NEW.item_id, NEW.uom_id, NEW.qty, NEW.qty_base, NEW.unit_cost, NEW.cost_center_id,
                NEW.batch_id, NEW.expected_qty, NEW.counted_qty, NEW.document_id)
               IS DISTINCT FROM
               (OLD.item_id, OLD.uom_id, OLD.qty, OLD.qty_base, OLD.unit_cost, OLD.cost_center_id,
                OLD.batch_id, OLD.expected_qty, OLD.counted_qty, OLD.document_id)
            THEN
                RAISE EXCEPTION 'Cannot modify a line on a % stock document (document id=%).',
                    document_status, line_document_id;
            END IF;
        END IF;
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER protect_posted_stock_document_trigger
    BEFORE UPDATE OR DELETE ON inventory_stockdocument
    FOR EACH ROW EXECUTE FUNCTION protect_posted_stock_document();

CREATE TRIGGER protect_posted_stock_document_line_trigger
    BEFORE INSERT OR UPDATE OR DELETE ON inventory_stockdocumentline
    FOR EACH ROW EXECUTE FUNCTION protect_posted_stock_document();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS protect_posted_stock_document_line_trigger ON inventory_stockdocumentline;
DROP TRIGGER IF EXISTS protect_posted_stock_document_trigger ON inventory_stockdocument;
DROP FUNCTION IF EXISTS protect_posted_stock_document();
"""


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0005_stockdocument_stockdocumentline"),
    ]

    operations = [
        migrations.RunSQL(SQL, reverse_sql=REVERSE_SQL),
    ]
