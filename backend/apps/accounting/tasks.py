from celery import shared_task

from .periods import create_next_fiscal_year_if_due
from .recurring import generate_due_installments


@shared_task
def create_due_fiscal_years():
    """Sprint 6.1 (decision 2): daily beat — any tenant whose latest
    fiscal year ends within 30 days (or, defensively, has none at all)
    gets its next year created automatically, `is_auto_created=True`."""
    return len(create_next_fiscal_year_if_due())


@shared_task
def generate_due_recurring_installments():
    """Sprint 6.4 (decision 10): daily beat, 01:00 UTC — every tenant's
    DUE installments whose period has already ended by today."""
    return generate_due_installments()
