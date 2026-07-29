# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Pricing.

One rule governs every rate in a generated scenario:

    purchase cost is the foundation; the selling rate is cost plus the family's
    gross margin.

Nothing is priced from an unrelated random distribution, which is what makes the
resulting profit and loss statement believable and what lets the validators
assert margin bands rather than merely assert that numbers exist.
"""

from __future__ import annotations

from typing import Any

from frappe_scenario.archetypes.base import Archetype, ItemFamily


def purchase_cost(random: Any, family: ItemFamily, price_scale: float, precision: int) -> float:
	"""Draw a purchase cost for one item within its family's cost band."""
	low, high = family.cost_range
	return round(random.uniform(low, high) * price_scale, precision)


def margin_for_item(random: Any, archetype: Archetype, family: ItemFamily, specification: dict) -> float:
	"""Draw a gross margin from the family's band, honouring specification overrides."""
	low, high = archetype.margin_range_for(family, specification)
	return round(random.uniform(low, high), 4)


def selling_rate(cost: float, margin: float, precision: int) -> float:
	"""Cost plus margin, expressed as a margin on the selling price.

	``margin`` is gross margin on revenue, so ``rate = cost / (1 - margin)``.
	This is the convention accountants read off a profit and loss statement.
	"""
	margin = min(max(float(margin), 0.0), 0.95)
	return round(float(cost) / (1.0 - margin), precision)


def gross_margin(cost: float, rate: float) -> float:
	"""Realised gross margin for a sold line."""
	if not rate:
		return 0.0
	return (float(rate) - float(cost)) / float(rate)


def discounted_rate(random: Any, rate: float, cost: float, max_discount: float, precision: int) -> float:
	"""Apply a negotiated discount that never pushes the rate below cost."""
	if max_discount <= 0:
		return rate
	floor = float(cost)
	discount = random.uniform(0.0, float(max_discount))
	candidate = round(float(rate) * (1.0 - discount), precision)
	return max(candidate, round(floor, precision))
