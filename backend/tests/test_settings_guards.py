"""Sprint 7.0 (CI #56 follow-up, decision 8): Django-settings-level boot
guards that only fire for a specific `CPS_ENVIRONMENT` value — these
run as a subprocess (`python -c "import django; django.setup()"`)
rather than in-process, because the guard itself is module-level code
in config/settings.py, evaluated once at import time; the already-
imported `django.conf.settings` in this very pytest process can't be
re-evaluated with a different environment after the fact.
"""

import os
import subprocess
import sys

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..")


def _settings_import_result(env_overrides):
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings", **env_overrides}
    return subprocess.run(
        [sys.executable, "-c", "import django; django.setup()"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )


def test_attachment_scan_must_be_enabled_in_production():
    result = _settings_import_result({"CPS_ENVIRONMENT": "production", "ATTACHMENT_SCAN_ENABLED": "false"})
    assert result.returncode != 0
    assert "ATTACHMENT_SCAN_ENABLED=false is not allowed in production" in result.stderr


def test_attachment_scan_enabled_boots_fine_in_production():
    result = _settings_import_result({"CPS_ENVIRONMENT": "production", "ATTACHMENT_SCAN_ENABLED": "true"})
    assert result.returncode == 0, result.stderr


def test_attachment_scan_disabled_boots_fine_outside_production():
    # The same "false" value that's refused in production is the
    # documented dev/CI escape hatch everywhere else — confirms the
    # guard is scoped to CPS_ENVIRONMENT=production specifically, not
    # to ATTACHMENT_SCAN_ENABLED=false on its own.
    result = _settings_import_result({"CPS_ENVIRONMENT": "ci", "ATTACHMENT_SCAN_ENABLED": "false"})
    assert result.returncode == 0, result.stderr
