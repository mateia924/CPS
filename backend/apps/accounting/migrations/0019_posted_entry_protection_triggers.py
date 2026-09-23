# Sprint 5.7 (CFO_REVIEW_1 C1): DB-level protection for a POSTED/
# REVERSED JournalEntry — Django-level checks (can_post, the ViewSet
# having no update/destroy action at all) already block every path
# *this application* exposes, but a trigger is the only guarantee that
# survives a future bug, a raw SQL script, or the Django admin. Two
# triggers:
#   1. protect_posted_journal_entry — rejects UPDATE/DELETE on a
#      POSTED/REVERSED accounting_journalentry row, except the single
#      allowed transition (status posted->reversed + reversed_at), and
#      rejects UPDATE/DELETE on any accounting_journalline row whose
#      entry is POSTED/REVERSED except the three bank-reconciliation
#      columns (reconciled_at/reconciled_by_id/bank_statement_line_id).
#   2. journal_line_balance_check — a DEFERRABLE INITIALLY DEFERRED
#      constraint trigger enforcing Σdebit = Σcredit (base currency)
#      per entry at COMMIT time, not per row-write (so a multi-line
#      bulk_create inside one transaction.atomic() only gets checked
#      once, at the end — exactly why every posting path in this
#      project already wraps its line-building in transaction.atomic).
from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION protect_posted_journal_entry() RETURNS TRIGGER AS $$
BEGIN
    IF TG_TABLE_NAME = 'accounting_journalentry' THEN
        IF TG_OP = 'DELETE' THEN
            IF OLD.status IN ('posted', 'reversed') THEN
                RAISE EXCEPTION 'Cannot delete a % journal entry (id=%).', OLD.status, OLD.id;
            END IF;
            RETURN OLD;
        END IF;

        -- UPDATE
        IF OLD.status IN ('posted', 'reversed') THEN
            IF (OLD.status = 'posted' AND NEW.status = 'reversed') OR NEW.status = OLD.status THEN
                -- status/reversed_at may change (the posted->reversed
                -- transition, or no-op re-saves) — every other column
                -- must stay exactly as it was.
                IF (NEW.tenant_id, NEW.legal_entity_id, NEW.date, NEW.memo, NEW.number, NEW.reference,
                    NEW.created_by_id, NEW.reverses_id, NEW.source_type, NEW.source_id,
                    NEW.content_type_id, NEW.object_id, NEW.currency, NEW.exchange_rate,
                    NEW.is_control_override, NEW.created_at)
                   IS DISTINCT FROM
                   (OLD.tenant_id, OLD.legal_entity_id, OLD.date, OLD.memo, OLD.number, OLD.reference,
                    OLD.created_by_id, OLD.reverses_id, OLD.source_type, OLD.source_id,
                    OLD.content_type_id, OLD.object_id, OLD.currency, OLD.exchange_rate,
                    OLD.is_control_override, OLD.created_at)
                THEN
                    RAISE EXCEPTION
                        'Cannot modify a % journal entry (id=%) except to reverse it.', OLD.status, OLD.id;
                END IF;
            ELSE
                RAISE EXCEPTION 'Cannot modify a % journal entry (id=%) except to reverse it.', OLD.status, OLD.id;
            END IF;
        END IF;
        RETURN NEW;
    END IF;

    -- accounting_journalline: look up the parent entry's status. NEW is
    -- not a bound record on DELETE (referencing NEW.* would raise
    -- "record new is not assigned yet"), so TG_OP is checked before any
    -- NEW.field access — never combined via COALESCE(NEW.x, OLD.x).
    DECLARE
        entry_status varchar;
        line_entry_id uuid;
    BEGIN
        IF TG_OP = 'DELETE' THEN
            line_entry_id := OLD.entry_id;
        ELSE
            line_entry_id := NEW.entry_id;
        END IF;
        SELECT status INTO entry_status FROM accounting_journalentry WHERE id = line_entry_id;

        IF entry_status IN ('posted', 'reversed') THEN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Cannot delete a line on a % journal entry (entry id=%).', entry_status, line_entry_id;
            END IF;
            -- UPDATE: only the three bank-reconciliation columns may change.
            IF (NEW.debit, NEW.credit, NEW.account_id, NEW.cost_center_id, NEW.credit_fc, NEW.debit_fc,
                NEW.party_id, NEW.description, NEW.currency, NEW.exchange_rate, NEW.entry_id)
               IS DISTINCT FROM
               (OLD.debit, OLD.credit, OLD.account_id, OLD.cost_center_id, OLD.credit_fc, OLD.debit_fc,
                OLD.party_id, OLD.description, OLD.currency, OLD.exchange_rate, OLD.entry_id)
            THEN
                RAISE EXCEPTION
                    'Cannot modify a line on a % journal entry (entry id=%) except its bank-reconciliation fields.',
                    entry_status, line_entry_id;
            END IF;
        END IF;
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER protect_posted_journal_entry_trigger
    BEFORE UPDATE OR DELETE ON accounting_journalentry
    FOR EACH ROW EXECUTE FUNCTION protect_posted_journal_entry();

CREATE TRIGGER protect_posted_journal_line_trigger
    BEFORE UPDATE OR DELETE ON accounting_journalline
    FOR EACH ROW EXECUTE FUNCTION protect_posted_journal_entry();

CREATE OR REPLACE FUNCTION check_journal_entry_balanced() RETURNS TRIGGER AS $$
DECLARE
    affected_entry_id uuid;
    total_debit numeric;
    total_credit numeric;
BEGIN
    IF TG_OP = 'DELETE' THEN
        affected_entry_id := OLD.entry_id;
    ELSE
        affected_entry_id := NEW.entry_id;
    END IF;

    SELECT COALESCE(SUM(debit), 0), COALESCE(SUM(credit), 0)
        INTO total_debit, total_credit
        FROM accounting_journalline
        WHERE entry_id = affected_entry_id;

    IF total_debit <> total_credit THEN
        RAISE EXCEPTION 'Journal entry % is not balanced at commit: debit % <> credit %',
            affected_entry_id, total_debit, total_credit;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER journal_line_balance_check
    AFTER INSERT OR UPDATE OR DELETE ON accounting_journalline
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION check_journal_entry_balanced();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS journal_line_balance_check ON accounting_journalline;
DROP FUNCTION IF EXISTS check_journal_entry_balanced();
DROP TRIGGER IF EXISTS protect_posted_journal_line_trigger ON accounting_journalline;
DROP TRIGGER IF EXISTS protect_posted_journal_entry_trigger ON accounting_journalentry;
DROP FUNCTION IF EXISTS protect_posted_journal_entry();
"""


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0018_backfill_control_account_flags"),
    ]

    operations = [
        migrations.RunSQL(SQL, reverse_sql=REVERSE_SQL),
    ]
