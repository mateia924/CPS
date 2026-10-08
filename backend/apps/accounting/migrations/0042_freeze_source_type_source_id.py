# Sprint 7.2.7 (§8.7, Deploy ب — owner decision 2026-10-08): the
# freeze. A Postgres trigger, not an application-level guard — same
# reasoning as protect_posted_journal_entry() (0019_posted_entry_
# protection_triggers): the application layer can't see a migration,
# a management command, or raw SQL, and every real incident this
# sprint found ("the sixth writer", the dynamically-built f-string
# value) was exactly a writer no application-level check or text
# search would have caught either.
#
# The launch condition is NOT "reject if non-blank" — rule 31's own
# historical rows legitimately CARRY a non-blank source_type/source_id
# forever (frozen, read-only trail). The actual invariant:
#   - INSERT with a non-blank value in either column -> reject (no new
#     row may ever get one, regardless of what it's set to).
#   - UPDATE where NEW.source_type IS DISTINCT FROM OLD.source_type,
#     or the same for source_id -> reject (a historical row's value
#     can never change, including being set now where it was blank).
#   - UPDATE that doesn't touch either column -> allow (a historical
#     row's every OTHER field already can't change on its own once
#     POSTED, per protect_posted_journal_entry() — this trigger only
#     ever has independent effect on a not-yet-posted row, or as a
#     second, explicit line of defense on a posted one).
# IS DISTINCT FROM throughout, never <> — source_id is nullable, and a
# plain <> against NULL is never true, silently waving through exactly
# the row class this trigger exists to protect.
from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION protect_source_type_source_id() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.source_type IS DISTINCT FROM '' OR NEW.source_id IS DISTINCT FROM NULL THEN
            RAISE EXCEPTION
                'Cannot write source_type/source_id on a new journal entry (id=%) — frozen historical trail; use produced_by/content_type/object_id instead.',
                NEW.id;
        END IF;
        RETURN NEW;
    END IF;

    -- UPDATE
    IF NEW.source_type IS DISTINCT FROM OLD.source_type OR NEW.source_id IS DISTINCT FROM OLD.source_id THEN
        RAISE EXCEPTION
            'Cannot modify source_type/source_id on journal entry (id=%) — frozen historical trail.',
            OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER protect_source_type_source_id_trigger
    BEFORE INSERT OR UPDATE ON accounting_journalentry
    FOR EACH ROW EXECUTE FUNCTION protect_source_type_source_id();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS protect_source_type_source_id_trigger ON accounting_journalentry;
DROP FUNCTION IF EXISTS protect_source_type_source_id();
"""


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0041_produced_by_not_blank_or_invalid"),
    ]

    operations = [
        migrations.RunSQL(SQL, reverse_sql=REVERSE_SQL),
    ]
