"""Sprint 6.6.3b (item a): the "platform" DB alias (config.settings.
DATABASES — the original, unrestricted role) is meant for exactly
three kinds of code: apps.platform itself, Django admin ModelAdmins
(apps/*/admin.py — reached via apps.tenants.routers.AdminBypassRouter,
never an explicit `.using(...)`), and management commands (which
already run as the unrestricted role for "default" too, so they have
no reason to reach for "platform" at all in practice). Anywhere else,
an explicit `.using("platform")` or `using="platform"` is a deliberate
bypass of RLS and needs its own named, reviewed reason — this is a
source-level scan (not a runtime registry walk like the other
structural tests in this suite), since the whole point is catching a
stray reference before it's ever exercised by a request at all.
"""

import re
from pathlib import Path

APPS_DIR = Path(__file__).resolve().parent.parent / "apps"

PLATFORM_PATTERN = re.compile(r"""\.using\(\s*["']platform["']\s*\)|using\s*=\s*["']platform["']""")

# Every file/line combination allowed to reach the "platform" alias
# outside apps/platform/, apps/*/admin.py, and apps/*/management/
# commands/*.py — each needs a real reason, reviewed by a human each
# time one is added.
PLATFORM_DB_EXEMPTIONS = {
    "attachments/views.py": "AttachmentDownloadView — a signed link with no tenant session context at all (AllowAny by design, apps.attachments.views's own docstring)",
}


def _is_exempt_by_location(relative_path: str) -> bool:
    if relative_path.startswith("platform/"):
        return True
    parts = relative_path.split("/")
    if len(parts) == 2 and parts[1] == "admin.py":
        return True
    if "management/commands/" in relative_path:
        return True
    return False


def test_platform_db_alias_is_only_reached_from_allowed_locations():
    violations = []
    for path in sorted(APPS_DIR.rglob("*.py")):
        relative_path = str(path.relative_to(APPS_DIR))
        if _is_exempt_by_location(relative_path):
            continue
        text = path.read_text()
        if not PLATFORM_PATTERN.search(text):
            continue
        if relative_path in PLATFORM_DB_EXEMPTIONS:
            continue
        violations.append(relative_path)

    assert not violations, (
        "File(s) reach the \"platform\" DB alias (.using(\"platform\") or "
        "using=\"platform\") outside apps/platform/, apps/*/admin.py, and "
        "management commands, without an entry in this file's own "
        f"PLATFORM_DB_EXEMPTIONS: {violations}"
    )


def test_platform_db_exemptions_are_still_accurate():
    for relative_path in PLATFORM_DB_EXEMPTIONS:
        path = APPS_DIR / relative_path
        assert path.exists(), f"{relative_path} is listed in PLATFORM_DB_EXEMPTIONS but no longer exists."
        assert PLATFORM_PATTERN.search(path.read_text()), (
            f"{relative_path} is listed in PLATFORM_DB_EXEMPTIONS but no longer "
            "reaches the \"platform\" alias at all — remove the stale entry."
        )
