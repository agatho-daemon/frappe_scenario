# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Scenario calendar.

Transaction dates are drawn on working days of the country pack's week and are
shaped by the archetype's seasonality, so a distributor of cooling equipment
shows a summer peak rather than a flat monthly line.
"""

from __future__ import annotations

import calendar
import datetime
from typing import Any

from frappe_scenario.locales.base import CountryPack


def month_starts(start: datetime.date, months: int) -> list[datetime.date]:
	"""First day of each month in the window, oldest first."""
	result: list[datetime.date] = []
	year, month = start.year, start.month
	for _ in range(months):
		result.append(datetime.date(year, month, 1))
		month += 1
		if month > 12:
			month = 1
			year += 1
	return result


def month_end(day: datetime.date) -> datetime.date:
	return datetime.date(day.year, day.month, calendar.monthrange(day.year, day.month)[1])


def as_iso(value: Any) -> str | None:
	"""ISO date string for a value Frappe may hand back as a date, datetime, or string."""
	if not value:
		return None
	if isinstance(value, datetime.datetime):
		return value.date().isoformat()
	if isinstance(value, datetime.date):
		return value.isoformat()
	return str(value)[:10]


def seasonal_counts(
	base_per_month: int,
	months: list[datetime.date],
	peak_months: list[int],
	peak_multiplier: float,
) -> list[int]:
	"""Monthly transaction counts with a deterministic seasonal uplift."""
	peak = set(peak_months or [])
	counts: list[int] = []
	for month in months:
		multiplier = float(peak_multiplier) if month.month in peak else 1.0
		counts.append(max(0, round(base_per_month * multiplier)))
	return counts


def dates_in_month(
	random: Any,
	pack: CountryPack,
	month: datetime.date,
	count: int,
	*,
	not_after: datetime.date | None = None,
) -> list[datetime.date]:
	"""``count`` sorted working-day dates inside ``month``."""
	last = month_end(month)
	if not_after and not_after < last:
		last = not_after
	if last < month:
		return []

	candidates = [
		month + datetime.timedelta(days=offset)
		for offset in range((last - month).days + 1)
		if pack.is_working_day(month + datetime.timedelta(days=offset))
	]
	if not candidates:
		candidates = [last]

	chosen = [candidates[random.randint(0, len(candidates) - 1)] for _ in range(count)]
	return sorted(chosen)


def offset_working_days(pack: CountryPack, day: datetime.date, days: int) -> datetime.date:
	"""Move forward ``days`` calendar days, then land on the next working day."""
	return pack.next_working_day(day + datetime.timedelta(days=max(int(days), 0)))


def clamp(day: datetime.date, low: datetime.date, high: datetime.date) -> datetime.date:
	return max(low, min(day, high))


def fiscal_years(start: datetime.date, end: datetime.date) -> list[tuple[datetime.date, datetime.date]]:
	"""Calendar-aligned fiscal years covering the window inclusively."""
	years: list[tuple[datetime.date, datetime.date]] = []
	for year in range(start.year, end.year + 1):
		years.append((datetime.date(year, 1, 1), datetime.date(year, 12, 31)))
	return years
