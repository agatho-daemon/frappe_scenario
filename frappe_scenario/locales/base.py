# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Country packs.

A country pack carries every locale-specific convention: currency and its
precision, the working week, address shape, telephone format, and the chart of
accounts to install.

Deliberate boundary: a country pack describes *conventions*, never *compliance*.
It does not create tax templates, national identifiers, or anything that could
be mistaken for a regulatory statement.
"""

from __future__ import annotations

import datetime
import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

#: Python ``date.weekday()`` values.
MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY = range(7)

_NON_HANDLE = re.compile(r"[^a-z0-9]+")


def latin_handle(value: str, *, fallback: str, separator: str = "-") -> str:
	"""An ASCII handle usable in an e-mail address.

	Frappe validates e-mail addresses against an ASCII grammar, so a name written
	in a non-Latin script cannot be used verbatim. Accented Latin folds to its
	base letters. A string with no ASCII remainder at all, such as an Arabic name,
	falls back to a short digest of the original: that keeps the handle unique and
	stable for a given seed instead of collapsing every such party onto one
	address, and it avoids pretending to transliterate a script properly.
	"""
	decomposed = unicodedata.normalize("NFKD", str(value))
	unmarked = "".join(char for char in decomposed if not unicodedata.combining(char))
	ascii_only = unmarked.encode("ascii", "ignore").decode("ascii").lower()
	cleaned = _NON_HANDLE.sub(separator, ascii_only).strip(separator)
	if cleaned:
		return cleaned
	digest = hashlib.blake2s(str(value).encode("utf-8"), digest_size=4).hexdigest()
	return f"{fallback}{separator}{digest}"


@dataclass
class CountryPack:
	"""Locale conventions for one country."""

	id: str
	country: str
	currency: str
	currency_precision: int = 2
	primary_locale: str = "en_US"
	secondary_locale: str = "en_US"

	#: Multiplier applied to archetype cost bands, which are expressed in
	#: neutral units roughly equivalent to one US dollar.
	price_scale: float = 1.0

	#: ``date.weekday()`` values that are not working days.
	weekend_days: tuple[int, ...] = (SATURDAY, SUNDAY)

	#: Chart of accounts template name, or ``None`` for the ERPNext standard one.
	chart_of_accounts: str | None = None

	#: Non-regulatory: purely a naming convention for generated company names.
	company_suffix: str = "Trading LLC"
	legal_forms: tuple[str, ...] = ("LLC", "Ltd.")
	business_words: tuple[str, ...] = (
		"Northwind",
		"Vertex",
		"Summit",
		"Harbor",
		"Crescent",
		"Meridian",
		"Anchor",
	)

	#: Telephone conventions. Numbers are synthetic and never dialable ranges we
	#: assert to be real.
	phone_country_code: str = "+1"
	phone_national_digits: int = 10
	phone_leading_digits: tuple[str, ...] = ("2", "3", "4")

	#: Reserved TLD; guarantees generated addresses can never reach a real inbox.
	email_domain_suffix: str = "example"

	regions: tuple[str, ...] = ()
	localities: tuple[str, ...] = ()

	#: Extra specification defaults contributed by this pack.
	extra_defaults: dict[str, Any] = field(default_factory=dict)

	def __post_init__(self) -> None:
		if self.email_domain_suffix != "example":
			raise ValueError("Synthetic e-mail domains must use the reserved .example suffix.")

	# -- working week --------------------------------------------------------
	@property
	def first_day_of_week(self) -> str:
		"""Weekday name Frappe's System Settings expects, derived from the weekend."""
		names = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
		for offset in range(7):
			candidate = (max(self.weekend_days) + 1 + offset) % 7 if self.weekend_days else 0
			if candidate not in self.weekend_days:
				return names[candidate]
		return "Monday"

	def is_working_day(self, day: datetime.date) -> bool:
		return day.weekday() not in self.weekend_days

	def next_working_day(self, day: datetime.date) -> datetime.date:
		candidate = day
		for _ in range(7):
			if self.is_working_day(candidate):
				return candidate
			candidate += datetime.timedelta(days=1)
		return day

	def previous_working_day(self, day: datetime.date) -> datetime.date:
		candidate = day
		for _ in range(7):
			if self.is_working_day(candidate):
				return candidate
			candidate -= datetime.timedelta(days=1)
		return day

	# -- generated conventions ----------------------------------------------
	def phone_number(self, random: Any) -> str:
		lead = random.choice(list(self.phone_leading_digits))
		remaining = self.phone_national_digits - len(lead)
		digits = "".join(str(random.randint(0, 9)) for _ in range(remaining))
		return f"{self.phone_country_code} {lead}{digits}"

	def email_domain(self, slug: str) -> str:
		return f"{latin_handle(slug, fallback='party')}.{self.email_domain_suffix}"

	def email_address(self, local_part: str, slug: str) -> str:
		local = latin_handle(local_part, fallback="contact", separator=".")
		return f"{local}@{self.email_domain(slug)}"

	def address(self, random: Any, faker: Any) -> dict[str, Any]:
		"""Return ERPNext Address field values for this country."""
		return {
			"address_line1": faker.street_address(),
			"address_line2": faker.secondary_address(),
			"city": faker.city(),
			"state": random.choice(list(self.regions)) if self.regions else None,
			"pincode": faker.postcode(),
			"country": self.country,
		}

	def company_name(self, random: Any) -> str:
		"""A plausible trading name for the scenario company."""
		return f"{random.choice(list(self.business_words))} {self.company_suffix}"

	# -- specification defaults ---------------------------------------------
	def specification_defaults(self) -> dict[str, Any]:
		defaults: dict[str, Any] = {"scenario": {"currency": self.currency}}
		for section, values in self.extra_defaults.items():
			defaults.setdefault(section, {})
			defaults[section].update(values)
		return defaults

	def describe(self) -> dict[str, Any]:
		return {
			"id": self.id,
			"country": self.country,
			"currency": self.currency,
			"currency_precision": self.currency_precision,
			"primary_locale": self.primary_locale,
			"secondary_locale": self.secondary_locale,
			"price_scale": self.price_scale,
			"weekend_days": list(self.weekend_days),
			"chart_of_accounts": self.chart_of_accounts,
			"phone_country_code": self.phone_country_code,
			"email_domain_suffix": self.email_domain_suffix,
			"legal_forms": list(self.legal_forms),
			"business_words": list(self.business_words),
			"regions": list(self.regions),
			"localities": list(self.localities),
		}
