"""Scheduler: next run honours time, time zone, day and the schedule period."""

from datetime import datetime, timezone

from services.scheduler_service import compute_next_run

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)  # Sunday 17:30 in India


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def test_daily_india_time():
    # 18:00 IST = 12:30 UTC, still today
    assert compute_next_run("Daily", NOW, {"time": "06:00 PM", "timezone": "Asia/Kolkata"}) == utc(2026, 10, 25, 12, 30)
    # 09:00 IST already passed today -> tomorrow 03:30 UTC
    assert compute_next_run("Daily", NOW, {"time": "09:00 AM", "timezone": "Asia/Kolkata"}) == utc(2026, 10, 26, 3, 30)


def test_weekly_weekday_and_zone():
    r = compute_next_run("Weekly", NOW, {"time": "09:00 AM", "timezone": "America/New_York", "weekday": "Monday"})
    assert r == utc(2026, 10, 26, 13, 0)  # 09:00 EDT


def test_monthly_specific_and_last_day():
    cfg = {"time": "08:00", "timezone": "Europe/London", "month_day": 31}
    assert compute_next_run("Monthly", NOW, cfg) == utc(2026, 10, 31, 8, 0)  # GMT after DST ends
    cfg = {"time": "08:00", "timezone": "UTC", "monthDayMode": "last"}
    assert compute_next_run("Monthly", utc(2026, 11, 30, 9, 0), cfg) == utc(2026, 12, 31, 8, 0)
    # day 31 in a 30-day month runs on the 30th
    assert compute_next_run("Monthly", utc(2026, 11, 1), {"time": "08:00", "month_day": 31}) == utc(2026, 11, 30, 8, 0)


def test_yearly():
    cfg = {"time": "10:00 AM", "timezone": "Australia/Sydney", "year_month": "February", "year_day": 29}
    assert compute_next_run("Yearly", NOW, cfg) == utc(2027, 2, 27, 23, 0)  # Feb 28 10:00 AEDT


def test_period_start_and_end():
    cfg = {"time": "09:00 AM", "timezone": "UTC"}
    assert compute_next_run("Daily", NOW, cfg, {"start_date": "2026-11-05"}) == utc(2026, 11, 5, 9, 0)
    assert compute_next_run("Daily", NOW, cfg, {"end_date": "2026-10-25", "never_expires": False}) is None
    assert compute_next_run("Daily", NOW, cfg, {"end_date": "2026-10-25", "never_expires": True}) == utc(2026, 10, 26, 9, 0)


def test_bad_input_falls_back():
    r = compute_next_run("Weekly", NOW, {"time": "nonsense", "timezone": "Mars/Base", "weekday": "Funday"})
    assert r == utc(2026, 10, 26, 9, 0)  # Monday 09:00 UTC
