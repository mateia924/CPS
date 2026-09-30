"""Sprint 6.6.2 (item 3): "الاختبار البنيوي يفحص كل مسار منصة" — every
view registered under apps.platform.urls must declare a
`permission_map` (apps.platform.permissions.HasPlatformRole's own opt-
in gate), or be in PLATFORM_RBAC_EXEMPTIONS with a real reason. Same
shape as test_structural_isolation.py/test_entity_scope_structural.py:
walk the actual registered views, fail loudly on anything unclassified.
"""

import apps.platform.urls as platform_urls

# Views that are deliberately NOT role-gated — each needs a real reason.
PLATFORM_RBAC_EXEMPTIONS = {
    "apps.platform.views.PlatformLoginView": "pre-auth by definition (AllowAny) — there is no role yet",
    "apps.platform.views.PlatformMeView": "reads only the caller's own identity, gated by IsAuthenticated alone",
    "rest_framework.routers.APIRootView": "DRF's own auto-generated router root — lists registered endpoints, nothing sensitive",
}


def _qualified_name(cls):
    return f"{cls.__module__}.{cls.__name__}"


def _registered_platform_view_classes():
    seen = {}
    for pattern in platform_urls.urlpatterns:
        cls = getattr(pattern.callback, "cls", None)
        if cls is not None:
            seen[_qualified_name(cls)] = cls
    return seen


def test_every_registered_platform_view_declares_a_permission_map_or_is_exempted():
    classes = _registered_platform_view_classes()
    for name in PLATFORM_RBAC_EXEMPTIONS:
        assert name in classes, (
            f"{name} is listed in PLATFORM_RBAC_EXEMPTIONS but no longer "
            "exists as a registered platform view — remove the stale entry."
        )

    violations = []
    for name, cls in classes.items():
        if name in PLATFORM_RBAC_EXEMPTIONS:
            continue
        if not getattr(cls, "permission_map", None):
            violations.append(name)

    assert not violations, (
        "Platform view(s) have no permission_map (apps.platform.permissions"
        ".HasPlatformRole's own opt-in gate) and aren't in "
        f"PLATFORM_RBAC_EXEMPTIONS with a reason: {violations}"
    )
