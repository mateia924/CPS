# Sprint 5.5 (block 5.5.2): 0020's UniqueConstraint on
# JournalLine.bank_statement_line was a real bug, caught while writing
# this block's grouped-match test — it enforced the OPPOSITE of what
# decision 4 requires. A plain FK column already guarantees "one
# journal line -> at most one statement line" on its own (nothing to
# add there); a UniqueConstraint on that same column additionally
# forces "each statement line <- at most one journal line", which is
# exactly the N:1 grouped-deposit case (a receipt + a bank-fee payment
# both matching one statement line) that decision 4 explicitly allows.
# Zero real rows ever had this field set (reconciliation didn't exist
# before this sprint), so dropping it is purely a schema fix.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0020_journal_line_bank_statement_line_unique'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='journalline',
            name='unique_journal_line_per_bank_statement_line',
        ),
    ]
