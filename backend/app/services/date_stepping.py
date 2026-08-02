import calendar
from datetime import date, timedelta
from typing import Optional


def advance_date(
    current: date, frequency: str, intended_day: Optional[int] = None,
) -> date:
    """Advance a date by the given frequency.

    For monthly/yearly, ``intended_day`` is the day the user actually wants
    (e.g. 31). We cap it to the target month's length so Feb clamps to 28/29,
    but subsequent months recover to 31/30 instead of sticking at 28.
    Falls back to ``current.day`` when not provided."""
    if frequency == "weekly":
        return current + timedelta(weeks=1)
    target_day = intended_day if intended_day else current.day
    if frequency == "yearly":
        year = current.year + 1
        day = min(target_day, calendar.monthrange(year, current.month)[1])
        return date(year, current.month, day)
    # monthly (default)
    month = current.month + 1
    year = current.year
    if month > 12:
        month = 1
        year += 1
    day = min(target_day, calendar.monthrange(year, month)[1])
    return date(year, month, day)
