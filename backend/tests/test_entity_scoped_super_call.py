"""Sprint 6.6.3b (item d): a small AST-based guard against the exact
MRO-shadowing bug discovered (and fixed project-wide) in sprint 6.6.1 —
a ViewSet that inherits EntityScopedMixin but defines its own
`get_queryset()` WITHOUT calling `super().get_queryset()` silently
bypasses the mixin's own filtering entirely, regardless of class
order, since Python always resolves the subclass's own method first.
Parses the actual source of each such `get_queryset()` (not just
checking it merely exists) so a future refactor can never reintroduce
the bug undetected — a plain text/regex scan would miss a `super(
ClassName, self).get_queryset()` spelling or false-positive on a
method that merely contains the substring in a comment.
"""

import ast
import inspect

from django.urls import get_resolver

from apps.common.viewsets import EntityScopedMixin


def _qualified_name(cls):
    return f"{cls.__module__}.{cls.__name__}"


def _registered_view_classes():
    def walk(patterns):
        classes = []
        for pattern in patterns:
            if hasattr(pattern, "url_patterns"):
                classes.extend(walk(pattern.url_patterns))
            else:
                cls = getattr(pattern.callback, "cls", None)
                if cls is not None:
                    classes.append(cls)
        return classes

    seen = {}
    for cls in walk(get_resolver().url_patterns):
        seen[_qualified_name(cls)] = cls
    return seen


def _calls_super_get_queryset(func) -> bool:
    """True if `func`'s own body contains a call of the shape
    `super().get_queryset()` or `super(SomeClass, self).get_queryset()`
    anywhere (not necessarily the whole return value — some overrides
    reasonably assign it to a local first)."""
    source = inspect.getsource(func)
    # Re-indent: inspect.getsource on a method keeps its original
    # indentation, which ast.parse rejects as a standalone module.
    dedented = "\n".join(line[4:] if line.startswith("    ") else line for line in source.splitlines())
    tree = ast.parse(dedented)

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get_queryset"
            and isinstance(node.func.value, ast.Call)
            and isinstance(node.func.value.func, ast.Name)
            and node.func.value.func.id == "super"
        ):
            return True
    return False


def test_every_entity_scoped_views_own_get_queryset_calls_super():
    classes = _registered_view_classes()
    violations = []
    for name, cls in classes.items():
        if not issubclass(cls, EntityScopedMixin):
            continue
        get_queryset = cls.__dict__.get("get_queryset")
        if get_queryset is None:
            # Doesn't override it at all — inherits EntityScopedMixin's
            # own get_queryset() directly, nothing to check.
            continue
        if not _calls_super_get_queryset(get_queryset):
            violations.append(name)

    assert not violations, (
        "View(s) inherit EntityScopedMixin but override get_queryset() "
        "without calling super().get_queryset() anywhere in it — this "
        "silently bypasses entity scoping entirely regardless of class "
        f"order (sprint 6.6.1's own MRO-shadowing bug): {violations}"
    )
