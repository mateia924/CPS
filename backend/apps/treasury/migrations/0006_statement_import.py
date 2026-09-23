# Sprint 5.5 (block 5.5.1, v2 decision 5): BankStatement/
# BankStatementLine were schema-only since sprint 4.4 with zero rows in
# every environment (dev included — verified before writing this
# migration) — hand-written rather than autodetector-generated only
# because of that interactive rename/default prompt, not because it
# touches real data. `statement_date` is replaced outright by
# `period_start`/`period_end` (a statement covers a range, not a single
# day); `matched` (bool) is replaced by `status` (the matching engine,
# block 5.5.2, needs a real UNMATCHED/MATCHED/IGNORED tri-state).
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("treasury", "0005_iban_change_request"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="bank",
            name="import_column_mapping",
            field=models.JSONField(blank=True, default=dict, verbose_name="import column mapping"),
        ),
        migrations.RemoveField(model_name="bankstatement", name="statement_date"),
        migrations.AddField(
            model_name="bankstatement",
            name="period_start",
            field=models.DateField(default="2020-01-01", verbose_name="period start"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="bankstatement",
            name="period_end",
            field=models.DateField(default="2020-01-01", verbose_name="period end"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="bankstatement",
            name="currency",
            field=models.CharField(default="", max_length=3, verbose_name="currency"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="bankstatement",
            name="import_format",
            field=models.CharField(blank=True, max_length=10, verbose_name="import format"),
        ),
        migrations.AddField(
            model_name="bankstatement",
            name="file_sha256",
            field=models.CharField(blank=True, max_length=64, verbose_name="file SHA-256"),
        ),
        migrations.AddField(
            model_name="bankstatement",
            name="line_count",
            field=models.PositiveIntegerField(default=0, verbose_name="line count"),
        ),
        migrations.AddField(
            model_name="bankstatement",
            name="imported_by",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="+", to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterModelOptions(
            name="bankstatement",
            options={"ordering": ["-period_end"]},
        ),
        migrations.AddConstraint(
            model_name="bankstatement",
            constraint=models.UniqueConstraint(
                condition=models.Q(("file_sha256", ""), _negated=True),
                fields=("tenant", "bank", "file_sha256"),
                name="unique_statement_file_sha256_per_bank",
            ),
        ),
        migrations.AddField(
            model_name="bankstatementline",
            name="line_no",
            field=models.PositiveIntegerField(default=0, verbose_name="line number"),
        ),
        migrations.RemoveField(model_name="bankstatementline", name="matched"),
        migrations.AddField(
            model_name="bankstatementline",
            name="status",
            field=models.CharField(
                choices=[("unmatched", "Unmatched"), ("matched", "Matched"), ("ignored", "Ignored")],
                default="unmatched", max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="bankstatementline",
            name="matched_by",
            field=models.CharField(
                blank=True, choices=[("auto", "Automatic"), ("manual", "Manual")], max_length=10
            ),
        ),
        migrations.AddField(
            model_name="bankstatementline",
            name="matched_by_user",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="+", to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="bankstatementline",
            name="matched_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="bankstatementline",
            name="ignored_reason",
            field=models.CharField(blank=True, max_length=255, verbose_name="ignored reason"),
        ),
        migrations.AlterModelOptions(
            name="bankstatementline",
            options={"ordering": ["date", "line_no"]},
        ),
    ]
