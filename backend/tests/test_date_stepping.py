from datetime import date

from app.services.date_stepping import advance_date


def test_advance_date_monthly():
    assert advance_date(date(2025, 1, 15), "monthly") == date(2025, 2, 15)
    assert advance_date(date(2025, 12, 10), "monthly") == date(2026, 1, 10)


def test_advance_date_monthly_overflow():
    # Jan 31 -> Feb should clamp to 28
    assert advance_date(date(2025, 1, 31), "monthly") == date(2025, 2, 28)
    # Leap year: Jan 31 -> Feb 29
    assert advance_date(date(2024, 1, 31), "monthly") == date(2024, 2, 29)


def test_advance_date_weekly():
    assert advance_date(date(2025, 1, 1), "weekly") == date(2025, 1, 8)
    assert advance_date(date(2025, 12, 29), "weekly") == date(2026, 1, 5)


def test_advance_date_yearly():
    assert advance_date(date(2025, 3, 15), "yearly") == date(2026, 3, 15)
    # Leap year: Feb 29 -> Feb 28 next year
    assert advance_date(date(2024, 2, 29), "yearly") == date(2025, 2, 28)


def test_advance_date_monthly_intended_day_recovers_after_february():
    # After Jan 31 clamps to Feb 28, advancing again must hit Mar 31 — not drift to Mar 28.
    feb = advance_date(date(2026, 1, 31), "monthly", intended_day=31)
    assert feb == date(2026, 2, 28)
    mar = advance_date(feb, "monthly", intended_day=31)
    assert mar == date(2026, 3, 31)
    apr = advance_date(mar, "monthly", intended_day=31)
    assert apr == date(2026, 4, 30)  # April has 30 days
    may = advance_date(apr, "monthly", intended_day=31)
    assert may == date(2026, 5, 31)


def test_advance_date_monthly_intended_day_30():
    # Day 30 pattern: Jan 30 -> Feb 28 -> Mar 30 (not Mar 28).
    feb = advance_date(date(2026, 1, 30), "monthly", intended_day=30)
    assert feb == date(2026, 2, 28)
    mar = advance_date(feb, "monthly", intended_day=30)
    assert mar == date(2026, 3, 30)


def test_advance_date_yearly_intended_day_leap_recovery():
    # Feb 29 on a leap year should recover to Feb 29 four years later, not stick at 28.
    y1 = advance_date(date(2024, 2, 29), "yearly", intended_day=29)
    assert y1 == date(2025, 2, 28)
    y2 = advance_date(y1, "yearly", intended_day=29)
    assert y2 == date(2026, 2, 28)
    y3 = advance_date(y2, "yearly", intended_day=29)
    assert y3 == date(2027, 2, 28)
    y4 = advance_date(y3, "yearly", intended_day=29)
    assert y4 == date(2028, 2, 29)
