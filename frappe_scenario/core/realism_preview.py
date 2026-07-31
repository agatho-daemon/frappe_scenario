# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Representative, insertion-free realism preview generation."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from frappe_scenario.archetypes import get_archetype
from frappe_scenario.core.quality import assess_preview
from frappe_scenario.core.random import RandomService
from frappe_scenario.locales import get_country_pack
from frappe_scenario.providers.support.naming import item_description, item_name
from frappe_scenario.providers.support.realism import RealismPipeline


def representative_preview(choices: dict[str, Any]) -> dict[str, Any]:
	"""Generate stable samples without inserting any Frappe document."""
	archetype = get_archetype(choices["archetype"])
	pack = get_country_pack(choices["country"])
	variation = int(choices.get("preview_variation") or 0)
	seed = _preview_seed(choices, variation)
	service = RandomService(seed, locales=[pack.primary_locale, pack.secondary_locale])
	random = service.random("preview", "realism")
	primary = service.faker("preview", "parties", pack.primary_locale)
	secondary = service.faker("preview", "parties_secondary", pack.secondary_locale)
	pipeline = RealismPipeline(
		random=random,
		primary_faker=primary,
		secondary_faker=secondary,
		country_pack=pack,
		archetype=archetype,
	)

	parties = []
	taken = set()
	for index in range(4):
		locale_source = "primary" if index % 2 == 0 else "secondary"
		name = pipeline.business_name(locale_source)
		while name in taken:
			name = pipeline.business_name(locale_source)
		taken.add(name)
		first, last = pipeline.person_name()
		parties.append(
			{
				"name": name,
				"contact": f"{first} {last}",
				"email": pack.email_address(f"{first}.{last}", name),
				"phone": pack.phone_number(random),
				"address": pipeline.address(),
			}
		)

	products = []
	families = archetype.families
	for index in range(min(5, max(len(families), 1))):
		family = families[index % len(families)]
		name = item_name(random, family)
		cost = round(random.uniform(*family.cost_range) * pack.price_scale, pack.currency_precision)
		margin = random.uniform(*family.margin_range)
		price = round(cost / max(1 - margin, 0.01), pack.currency_precision)
		products.append(
			{
				"name": name,
				"family": family.title,
				"uom": family.uom,
				"cost": cost,
				"selling_price": price,
				"currency": choices["currency"],
				"description": item_description(family, name),
			}
		)

	stories = []
	for index in range(min(2, len(parties), len(products))):
		quantity = random.randint(1, 6)
		product = products[index]
		stories.append(
			{
				"customer": parties[index]["name"],
				"item": product["name"],
				"quantity": quantity,
				"order_value": round(quantity * product["selling_price"], pack.currency_precision),
				"currency": choices["currency"],
				"lifecycle": ["Sales Order", "Delivery Note", "Sales Invoice", "Payment Entry"],
			}
		)

	samples = {
		"country": pack.country,
		"variation": variation,
		"seed": seed,
		"parties": parties,
		"products": products,
		"transaction_stories": stories,
	}
	samples["quality"] = assess_preview(samples)
	return samples


def _preview_seed(choices: dict[str, Any], variation: int) -> int:
	material = {
		key: value for key, value in choices.items() if key not in {"preview_variation", "history_months"}
	}
	material["preview_variation"] = variation
	digest = hashlib.blake2b(
		json.dumps(material, sort_keys=True, default=str).encode("utf-8"),
		digest_size=8,
	).digest()
	return int.from_bytes(digest, "big") % (1 << 63)
