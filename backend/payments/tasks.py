import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from .services_settlements import generate_settlements_for_week

logger = logging.getLogger(__name__)


@shared_task
def generate_weekly_settlements():
    today = timezone.localdate()
    current_week_start = today - timedelta(days=today.weekday())
    week_start = current_week_start - timedelta(days=7)
    week_end = week_start + timedelta(days=6)

    result = generate_settlements_for_week(week_start=week_start, week_end=week_end)
    logger.info(
        "Weekly settlement task completed for %s to %s. Created=%s IDs=%s",
        week_start,
        week_end,
        result["count"],
        result["created_settlement_ids"],
    )
    return result
