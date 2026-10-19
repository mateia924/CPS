"""2026-10-19, before deploying 7.2.9 to live: an explicit EMAIL_BACKEND
in the environment selects Django's email backend. Until now settings.py
never read that variable — a line in live's .env would have changed
nothing while every password-reset link kept going to the worker log.
Live sets the dummy backend until Phase B; Phase B names its real
provider's backend through the same variable.

Each case loads settings in a fresh interpreter with its own environment
(settings are read once per process), and pytest-django's locmem
override never reaches it.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
DUMMY = "django.core.mail.backends.dummy.EmailBackend"
CONSOLE = "django.core.mail.backends.console.EmailBackend"
SMTP = "django.core.mail.backends.smtp.EmailBackend"
_SENTINEL = "-".join(["never", "logged", "4711"])

_PROBE = (
    "import django; django.setup(); "
    "from django.conf import settings; print('selected=' + settings.EMAIL_BACKEND)"
)


def _load(**overrides):
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("EMAIL_BACKEND", "EMAIL_HOST", "EMAIL_HOST_PASSWORD", "CPS_ENVIRONMENT")
    }
    env.update(DJANGO_SETTINGS_MODULE="config.settings", **overrides)
    result = subprocess.run(
        [sys.executable, "-c", _PROBE], cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    selected = [line for line in result.stdout.splitlines() if line.startswith("selected=")]
    return selected[-1].removeprefix("selected="), result.stdout + result.stderr


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"EMAIL_BACKEND": DUMMY}, DUMMY),
        ({"EMAIL_BACKEND": DUMMY, "EMAIL_HOST": "smtp.example.test"}, DUMMY),
        ({}, CONSOLE),
        ({"EMAIL_HOST": "smtp.example.test"}, SMTP),
    ],
    ids=["env-dummy", "env-wins-over-email-host", "unset-falls-back-to-console", "unset-with-host-is-smtp"],
)
def test_an_explicit_email_backend_in_the_environment_wins(overrides, expected):
    selected, _output = _load(**overrides)
    assert selected == expected


def test_staging_keeps_its_hard_console_override_whatever_the_env_file_says():
    selected, _output = _load(CPS_ENVIRONMENT="staging", EMAIL_BACKEND=SMTP, EMAIL_HOST="smtp.example.test")
    assert selected == CONSOLE


def test_startup_names_the_selected_backend_and_no_credential():
    _selected, output = _load(
        EMAIL_BACKEND=DUMMY, EMAIL_HOST="smtp.example.test", EMAIL_HOST_PASSWORD=_SENTINEL
    )
    assert f"email backend: {DUMMY}" in output
    assert _SENTINEL not in output
    assert "smtp.example.test" not in output
