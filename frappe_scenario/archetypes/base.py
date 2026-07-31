# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Business archetypes.

An archetype answers "what kind of business is this?" It supplies coherent
defaults for the specification and the domain vocabulary providers need: item
families, their commercial character, their margin bands, and their lead times.

Archetypes hold *data*, never generation logic. That keeps the same providers
usable for a distributor, a retailer, or a service company.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from frappe_scenario.core.errors import SpecificationError

#: Commercial character of a family. Used by validators to assert that equipment
#: is sold on thinner margins than spares and services.
FamilyKind = Literal["equipment", "controls", "accessory", "consumable", "spare", "service"]

#: Ordering used when a validator compares margin bands between kinds.
KIND_MARGIN_RANK: dict[str, int] = {
	"equipment": 0,
	"controls": 1,
	"accessory": 2,
	"consumable": 3,
	"spare": 4,
	"service": 5,
}


@dataclass(frozen=True)
class ItemFamily:
	"""One coherent group of sellable things."""

	key: str
	title: str
	kind: FamilyKind
	item_group: str
	uom: str
	#: Purchase cost band in archetype-neutral units. The country pack scales it.
	cost_range: tuple[float, float]
	#: Gross margin band applied on top of purchase cost.
	margin_range: tuple[float, float]
	#: Supplier lead time band in days.
	lead_time_days: tuple[int, int]
	#: Relative share of the item catalog.
	catalog_weight: float = 1.0
	#: Relative share of sales demand.
	demand_weight: float = 1.0
	#: Services are non-stock; everything else is maintained in inventory.
	is_stock_item: bool = True
	#: Typical line quantity band on a sales order.
	quantity_range: tuple[int, int] = (1, 5)
	descriptors: tuple[str, ...] = ()

	def as_dict(self) -> dict[str, Any]:
		return {
			"key": self.key,
			"title": self.title,
			"kind": self.kind,
			"item_group": self.item_group,
			"uom": self.uom,
			"cost_range": list(self.cost_range),
			"margin_range": list(self.margin_range),
			"lead_time_days": list(self.lead_time_days),
			"catalog_weight": self.catalog_weight,
			"demand_weight": self.demand_weight,
			"is_stock_item": self.is_stock_item,
			"quantity_range": list(self.quantity_range),
		}


@dataclass
class Archetype:
	"""Declarative description of a business shape."""

	id: str
	title: str
	description: str
	default_country: str
	industry: str = "Distribution"
	item_groups: list[str] = field(default_factory=list)
	warehouses: list[dict[str, str]] = field(default_factory=list)
	families: list[ItemFamily] = field(default_factory=list)
	customer_segments: dict[str, float] = field(default_factory=dict)
	payment_terms: dict[str, float] = field(default_factory=dict)
	peak_months: list[int] = field(default_factory=list)
	peak_multiplier: float = 1.0
	cash_sales_ratio: float = 0.2
	gross_margin_range: tuple[float, float] = (0.15, 0.45)
	uoms: list[str] = field(default_factory=list)
	supported_modules: tuple[str, ...] = ()
	operational_ratios: dict[str, Any] = field(default_factory=dict)
	learning_paths: tuple[str, ...] = ()
	validation_expectations: tuple[str, ...] = ()
	required_capabilities: tuple[str, ...] = ()
	lifecycle_validated: bool = False
	unavailable_reason: str | None = None

	def __post_init__(self) -> None:
		if not self.families:
			raise SpecificationError(f"Archetype {self.id!r} must declare item families.")
		if self.lifecycle_validated and self.unavailable_reason:
			raise SpecificationError(f"Ready archetype {self.id!r} cannot declare an unavailable reason.")
		if self.lifecycle_validated and not all(
			(self.supported_modules, self.learning_paths, self.validation_expectations)
		):
			raise SpecificationError(
				f"Ready archetype {self.id!r} must declare modules, lessons, and validation expectations."
			)

	# -- lookup --------------------------------------------------------------
	def family(self, key: str) -> ItemFamily:
		for candidate in self.families:
			if candidate.key == key:
				return candidate
		raise SpecificationError(
			f"Archetype {self.id!r} has no item family {key!r}.",
			phase="resolve",
			details={"available": [candidate.key for candidate in self.families]},
		)

	def selected_families(self, specification: dict[str, Any]) -> list[ItemFamily]:
		"""Families named by the specification, in specification order."""
		keys = (specification.get("catalog") or {}).get("families") or [
			candidate.key for candidate in self.families
		]
		return [self.family(key) for key in keys]

	def margin_range_for(self, family: ItemFamily, specification: dict[str, Any]) -> tuple[float, float]:
		"""Resolved margin band: specification override wins over archetype data."""
		catalog = specification.get("catalog") or {}
		override = (catalog.get("family_margin_overrides") or {}).get(family.key)
		if override:
			return (float(override[0]), float(override[1]))
		return family.margin_range

	# -- specification defaults ---------------------------------------------
	def defaults(self, scale: str) -> dict[str, Any]:
		"""Specification fragments this archetype contributes when unset."""
		return {
			"company": {
				"industry": self.industry,
				"enable_perpetual_inventory": True,
				"warehouses": [dict(warehouse) for warehouse in self.warehouses],
			},
			"parties": {
				"customer_segments": dict(self.customer_segments),
				"payment_terms": dict(self.payment_terms),
				"cash_sales_ratio": self.cash_sales_ratio,
			},
			"catalog": {
				"families": [family.key for family in self.families],
				"gross_margin_range": list(self.gross_margin_range),
				"family_margin_overrides": {
					family.key: list(family.margin_range) for family in self.families
				},
			},
			"operations": {
				"seasonality": {
					"peak_months": list(self.peak_months),
					"peak_multiplier": self.peak_multiplier,
				},
				**dict(self.operational_ratios),
			},
		}

	def describe(self) -> dict[str, Any]:
		return {
			"id": self.id,
			"title": self.title,
			"description": self.description,
			"default_country": self.default_country,
			"industry": self.industry,
			"item_groups": list(self.item_groups),
			"warehouses": [dict(warehouse) for warehouse in self.warehouses],
			"families": [family.as_dict() for family in self.families],
			"customer_segments": dict(self.customer_segments),
			"payment_terms": dict(self.payment_terms),
			"peak_months": list(self.peak_months),
			"peak_multiplier": self.peak_multiplier,
			"uoms": list(self.uoms),
			"supported_modules": list(self.supported_modules),
			"operational_ratios": dict(self.operational_ratios),
			"learning_paths": list(self.learning_paths),
			"validation_expectations": list(self.validation_expectations),
			"required_capabilities": list(self.required_capabilities),
			"lifecycle_validated": self.lifecycle_validated,
			"available": self.lifecycle_validated,
			"unavailable_reason": self.unavailable_reason,
		}
