# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Kuwait country pack.

Every Kuwait-specific convention lives here and nowhere else. Providers stay
country-agnostic and ask the pack.

Explicitly out of scope, by design:

* no civil identification numbers of any kind;
* no VAT, excise, or other tax templates, and no regulatory claims;
* the ERPNext standard chart of accounts is used, because no verified Kuwait
  chart ships with ERPNext.

Addresses follow the everyday Kuwaiti postal shape (governorate, area, block,
street, building, floor or office, optional P.O. box). Telephone numbers use the
``+965`` country code with eight synthetic digits.
"""

from __future__ import annotations

from typing import Any

from frappe_scenario.locales.base import FRIDAY, SATURDAY, CountryPack

GOVERNORATES = (
	"Al Asimah",
	"Hawalli",
	"Al Farwaniyah",
	"Al Ahmadi",
	"Al Jahra",
	"Mubarak Al-Kabeer",
)

AREAS = (
	"Salmiya",
	"Hawally",
	"Jabriya",
	"Salwa",
	"Shuwaikh Industrial",
	"Shuwaikh",
	"Sharq",
	"Qibla",
	"Mirqab",
	"Farwaniya",
	"Khaitan",
	"Ardiya",
	"Sabhan Industrial",
	"Fahaheel",
	"Mangaf",
	"Mahboula",
	"Sabah Al Salem",
	"Rumaithiya",
	"Bayan",
	"Mishref",
	"Jahra",
	"Sulaibiya",
	"Ahmadi",
)

STREET_NAMES = (
	"Street 1",
	"Street 3",
	"Street 5",
	"Street 7",
	"Street 11",
	"Street 14",
	"Street 20",
	"Street 25",
	"First Ring Road",
	"Fourth Ring Road",
	"Airport Road",
	"Fahaheel Expressway",
	"Ghazali Street",
	"Salem Al Mubarak Street",
	"Tunis Street",
)

BUSINESS_WORDS = (
	"Al Bahar",
	"Al Nasser",
	"Al Marzouq",
	"Al Sayer",
	"Al Rashed",
	"Gulf Breeze",
	"Desert Cool",
	"Arabian Climate",
	"Bayan",
	"Mirqab",
	"Kuwait Cooling",
	"Al Qurain",
)


class KuwaitPack(CountryPack):
	"""Kuwait conventions, including its structured address shape."""

	def address(self, random: Any, faker: Any) -> dict[str, Any]:
		area = random.choice(list(AREAS))
		block = random.randint(1, 12)
		street = random.choice(list(STREET_NAMES))
		building = random.randint(1, 120)

		line2_parts: list[str] = []
		if random.chance(0.6):
			line2_parts.append(f"Floor {random.randint(1, 12)}")
		if random.chance(0.5):
			line2_parts.append(f"Office {random.randint(1, 40)}")
		if random.chance(0.35):
			line2_parts.append(f"P.O. Box {random.randint(1000, 99999)}")

		return {
			"address_line1": f"Block {block}, {street}, Building {building}",
			"address_line2": ", ".join(line2_parts) or area,
			"city": area,
			"state": random.choice(list(GOVERNORATES)),
			"pincode": f"{random.randint(10000, 99999)}",
			"country": self.country,
		}

	def company_name(self, random: Any) -> str:
		return f"{random.choice(list(BUSINESS_WORDS))} {self.company_suffix}"


COUNTRY_PACK = KuwaitPack(
	id="kuwait",
	country="Kuwait",
	currency="KWD",
	currency_precision=3,
	# Arabic-capable primary locale with an English secondary locale so party
	# names, contacts, and free text can be generated in either script.
	primary_locale="ar_AA",
	secondary_locale="en_US",
	# Archetype cost bands are expressed in neutral units near one US dollar.
	price_scale=0.31,
	# Working week is Sunday to Thursday.
	weekend_days=(FRIDAY, SATURDAY),
	chart_of_accounts=None,
	company_suffix="Trading Company W.L.L.",
	phone_country_code="+965",
	phone_national_digits=8,
	phone_leading_digits=("2", "5", "6", "9"),
	email_domain_suffix="example",
	regions=GOVERNORATES,
	localities=AREAS,
	extra_defaults={
		"parties": {"cash_sales_ratio": 0.25},
	},
)
