"""Sprint 7.0 (6.6.10, rule 11): negative tests for guards — each one
proves the guard actually REFUSES the wrong case, not just that it
allows the right one. Grows as the rest of 6.6.10's five items land
(deploy.sh's own guards, backup.sh's production-failure severity, the
four frontend structural checks, test_rls_structural's own negative
case, and the pytest-concurrency check) — this file is their shared
home, run under `make test` like everything else here.
"""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


@pytest.mark.django_db
def test_seed_perf_refuses_to_run_on_staging(monkeypatch):
    """apps.accounting.management.commands.seed_perf's own guard
    (CPS_ENVIRONMENT in {staging, production} -> CommandError) is what
    test_open_period_structural.py's own exemption for this file rests
    on — this proves that guard is real code, not just a docstring
    claim (the exact distortion rule 11 exists to catch)."""
    monkeypatch.setenv("CPS_ENVIRONMENT", "staging")
    with pytest.raises(CommandError, match="seed_perf refuses to run on staging/production"):
        call_command("seed_perf", "--tenant", "guard-test-should-never-be-created", "--lines", "2")


@pytest.mark.django_db
def test_seed_perf_refuses_to_run_on_production(monkeypatch):
    monkeypatch.setenv("CPS_ENVIRONMENT", "production")
    with pytest.raises(CommandError, match="seed_perf refuses to run on staging/production"):
        call_command("seed_perf", "--tenant", "guard-test-should-never-be-created", "--lines", "2")
