"""ISO week helpers.

The archive is named by ISO week (`2026-W39.md`) because that is the convention this
repo's reports already use and it sorts lexicographically. ISO weeks start on Monday,
which is also how the user's work week is framed.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Tuple

WEEK_RE = re.compile(r"^(\d{4})-W(\d{1,2})$", re.I)
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_date(value: str) -> _dt.date:
    """Parse YYYY-MM-DD, or accept 'today'/'yesterday' for convenience."""
    v = (value or "").strip().lower()
    today = _dt.date.today()
    if v in ("today", ""):
        return today
    if v == "yesterday":
        return today - _dt.timedelta(days=1)
    m = DATE_RE.match(v)
    if not m:
        raise ValueError("not a date: %r (expected YYYY-MM-DD)" % value)
    return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def week_of(d: _dt.date) -> str:
    """ISO week label for a date, e.g. '2026-W39'."""
    iso = d.isocalendar()
    return "%04d-W%02d" % (iso[0], iso[1])


def parse_week(value: str) -> Tuple[int, int]:
    m = WEEK_RE.match((value or "").strip())
    if not m:
        raise ValueError("not a week: %r (expected YYYY-Www)" % value)
    return int(m.group(1)), int(m.group(2))


def week_bounds(value: str) -> Tuple[_dt.date, _dt.date]:
    """First (Monday) and last (Sunday) date of an ISO week."""
    year, week = parse_week(value)
    monday = _dt.date.fromisocalendar(year, week, 1)
    return monday, monday + _dt.timedelta(days=6)


def week_dates(value: str) -> list:
    start, _ = week_bounds(value)
    return [start + _dt.timedelta(days=i) for i in range(7)]


def week_label(value: str) -> str:
    """'2026-W39' -> '2026 W39（09/21 – 09/27）' for report headers."""
    start, end = week_bounds(value)
    return "%s（%s – %s）" % (value.replace("-W", " W"),
                             start.strftime("%m/%d"), end.strftime("%m/%d"))


def current_week() -> str:
    return week_of(_dt.date.today())


def previous_week(value: str) -> str:
    start, _ = week_bounds(value)
    return week_of(start - _dt.timedelta(days=7))


def next_week(value: str) -> str:
    _, end = week_bounds(value)
    return week_of(end + _dt.timedelta(days=1))