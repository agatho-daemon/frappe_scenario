# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Generic international country pack.

The neutral fallback used when a specification names a country that has no
dedicated pack. It leans entirely on Faker's default address and telephone
providers and makes no local claims.
"""

from __future__ import annotations

from frappe_scenario.locales.base import CountryPack

COUNTRY_PACK = CountryPack(
	id="generic_international",
	country="United States",
	currency="USD",
	currency_precision=2,
	primary_locale="en_US",
	secondary_locale="en_GB",
	price_scale=1.0,
	chart_of_accounts=None,
	company_suffix="Trading LLC",
	phone_country_code="+1",
	phone_national_digits=10,
	phone_leading_digits=("2", "3", "4", "6", "7"),
	email_domain_suffix="example",
)
