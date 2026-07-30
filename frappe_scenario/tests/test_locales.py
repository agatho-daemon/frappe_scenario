# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Country pack behaviour that does not need a site."""

import datetime

import pytest

from frappe_scenario.locales.base import CountryPack, latin_handle

pytestmark = pytest.mark.pure


def _pack(**kwargs) -> CountryPack:
	defaults = {"id": "test", "country": "Testland", "currency": "TST"}
	return CountryPack(**{**defaults, **kwargs})


@pytest.mark.parametrize(
	("value", "expected"),
	[
		("Rodriguez, Dickerson and Scott", "rodriguez-dickerson-and-scott"),
		("Désert Cool", "desert-cool"),
		("  spaced   out  ", "spaced-out"),
	],
)
def test_latin_handle_folds_to_an_ascii_slug(value, expected):
	assert latin_handle(value, fallback="party") == expected


def test_a_non_latin_name_gets_a_distinct_handle_rather_than_a_shared_fallback():
	"""Arabic names must not all collapse onto one handle.

	They carry no ASCII letters, so a naive slug yields an empty string and every
	such party would end up sharing a domain and colliding on e-mail address.
	"""
	first = latin_handle("قيس عيلان", fallback="party")
	second = latin_handle("بنو فراس", fallback="party")
	assert first != second
	assert first.startswith("party-")
	assert second.startswith("party-")


def test_latin_handle_is_stable_for_the_same_input():
	assert latin_handle("قيس عيلان", fallback="party") == latin_handle("قيس عيلان", fallback="party")


def test_email_addresses_are_always_ascii():
	pack = _pack()
	address = pack.email_address("محاسبة", "قيس عيلان")
	assert address.isascii()
	assert address.count("@") == 1


def test_the_weekend_decides_which_days_are_working_days():
	# Friday and Saturday, as in much of the Gulf.
	pack = _pack(weekend_days=(4, 5))
	friday = datetime.date(2026, 1, 30)
	sunday = datetime.date(2026, 2, 1)
	assert not pack.is_working_day(friday)
	assert pack.is_working_day(sunday)
	assert pack.next_working_day(friday) == sunday
	assert pack.previous_working_day(friday) == datetime.date(2026, 1, 29)


def test_next_working_day_leaves_a_working_day_alone():
	pack = _pack(weekend_days=(4, 5))
	thursday = datetime.date(2026, 1, 29)
	assert pack.next_working_day(thursday) == thursday
