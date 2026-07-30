# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Scale profiles.

A profile only supplies defaults. Anything explicitly present in the
specification always wins, which is what ``custom`` relies on.
"""

from __future__ import annotations

from typing import Any

from frappe_scenario.core.errors import SpecificationError

SCALE_PROFILES: dict[str, dict[str, Any]] = {
	"smoke": {
		"description": "One company and one example of each critical lifecycle. Under 200 records.",
		"history_months": 2,
		"parties": {"customers": 6, "suppliers": 4, "leads": 4},
		"catalog": {"item_count": 12},
		"operations": {"sales_orders_per_month": 4, "purchase_orders_per_month": 2},
		"accounting": {"bank_accounts": 1},
	},
	"small": {
		"description": "About 10 customers, 8 suppliers, 30 items and 3 months of history.",
		"history_months": 3,
		"parties": {"customers": 10, "suppliers": 8, "leads": 8},
		"catalog": {"item_count": 30},
		"operations": {"sales_orders_per_month": 8, "purchase_orders_per_month": 4},
		"accounting": {"bank_accounts": 1},
	},
	"medium": {
		"description": "About 75 customers, 30 suppliers, 250 items and 2 years of history.",
		"history_months": 24,
		"parties": {"customers": 75, "suppliers": 30, "leads": 40},
		"catalog": {"item_count": 250},
		"operations": {"sales_orders_per_month": 18, "purchase_orders_per_month": 8},
		"accounting": {"bank_accounts": 2},
	},
	"large": {
		"description": "About 500 customers, 150 suppliers, 2000 items and 5 years of history.",
		"history_months": 60,
		"parties": {"customers": 500, "suppliers": 150, "leads": 200},
		"catalog": {"item_count": 2000},
		"operations": {"sales_orders_per_month": 60, "purchase_orders_per_month": 25},
		"accounting": {"bank_accounts": 3},
	},
	"custom": {
		"description": "Explicit counts and dates supplied by the specification.",
		"history_months": 3,
		"parties": {"customers": 10, "suppliers": 8, "leads": 8},
		"catalog": {"item_count": 30},
		"operations": {"sales_orders_per_month": 8, "purchase_orders_per_month": 4},
		"accounting": {"bank_accounts": 1},
	},
}

DEFAULT_SCALE = "smoke"


def get_scale_profile(scale: str) -> dict[str, Any]:
	"""The profile for a named scale.

	An unknown name is an error rather than a quiet fallback: substituting the
	default would hand back a far smaller dataset than was asked for, and the
	mismatch would only surface much later as puzzling record counts.
	"""
	profile = SCALE_PROFILES.get(scale)
	if profile is None:
		known = ", ".join(sorted(SCALE_PROFILES))
		raise SpecificationError(
			f"Unknown scale '{scale}'. Known scales are: {known}.",
			phase="plan",
			details={"scale": scale, "known": sorted(SCALE_PROFILES)},
		)
	return profile


def describe_scale_profiles() -> list[dict[str, Any]]:
	return [
		{
			"id": name,
			"description": profile["description"],
			"history_months": profile["history_months"],
			"customers": profile["parties"]["customers"],
			"suppliers": profile["parties"]["suppliers"],
			"items": profile["catalog"]["item_count"],
		}
		for name, profile in SCALE_PROFILES.items()
	]
