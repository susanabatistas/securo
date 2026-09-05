import calendar
from datetime import date, timedelta
from typing import Optional


def _advance_months(current: date, months: int, intended_day: int) -> date:
    """Advance by calendar months, clamping only in a shorter target month."""
    month_index = current.month - 1 + months
    year = current.year + month_index // 12
    month = month_index % 12 + 1
    day = min(intended_day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def advance_date(
    current: date, frequency: str, intended_day: Optional[int] = None,
) -> date:
    """Advance a date by the given frequency.

    For monthly, quarterly, semiannual, and yearly recurrences, ``intended_day`` is the day
    the user actually wants (e.g. 31). We cap it to the target month's length
    so short months clamp, but subsequent occurrences recover to the intended
    day when it exists again. Falls back to ``current.day`` when not provided.
    """
    if frequency == "weekly":
        return current + timedelta(weeks=1)
    if frequency == "biweekly":
        return current + timedelta(weeks=2)

    target_day = intended_day if intended_day else current.day
    if frequency == "monthly":
        return _advance_months(current, 1, target_day)
    if frequency == "quarterly":
        return _advance_months(current, 3, target_day)
    if frequency == "semiannual":
        return _advance_months(current, 6, target_day)
    if frequency == "yearly":
        year = current.year + 1
        day = min(target_day, calendar.monthrange(year, current.month)[1])
        return date(year, current.month, day)

    # Preserve the existing monthly fallback for unknown legacy values.
    return _advance_months(current, 1, target_day)


def adjust_weekend_date(
    nominal_date: date, weekend_adjustment: str = "none"
) -> date:
    """Return the effective date without changing the nominal schedule date."""
    if weekend_adjustment not in ("none", "previous_friday", "next_monday"):
        raise ValueError(f"Unsupported weekend adjustment: {weekend_adjustment}")

    weekday = nominal_date.weekday()
    if weekend_adjustment == "none" or weekday < calendar.SATURDAY:
        return nominal_date
    if weekend_adjustment == "previous_friday":
        return nominal_date - timedelta(days=weekday - calendar.FRIDAY)
    return nominal_date + timedelta(days=7 - weekday)
