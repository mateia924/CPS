import pytest


@pytest.mark.django_db
def test_migrations_apply_cleanly():
    """No assertions needed: requesting the db fixture forces
    pytest-django to create the test database by running every app's
    migrations. If any migration is broken, this test fails at setup."""
