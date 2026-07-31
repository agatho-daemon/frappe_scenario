# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""ERPNext catalog provider.

Warehouses, item groups, units of measure, items, price lists, and item prices.

The pricing rule is the important part: a purchase cost is drawn from the
family's cost band, and the selling rate is derived from that cost plus the
family's gross margin. No selling rate is ever an unrelated random number, which
is what makes the resulting margins defensible.
"""

from __future__ import annotations

from typing import Any

import frappe

from frappe_scenario.archetypes.base import ItemFamily
from frappe_scenario.core.context import ScenarioContext
from frappe_scenario.core.errors import ProviderError
from frappe_scenario.core.provider import (
	CapabilityDeclaration,
	ProviderResult,
	ScenarioPlan,
	ScenarioProvider,
)
from frappe_scenario.core.validation import ValidationResult
from frappe_scenario.providers.erpnext_foundation import ACCOUNTS, COMPANY
from frappe_scenario.providers.support import erpnext_tools as tools
from frappe_scenario.providers.support.naming import item_code, item_description, item_name
from frappe_scenario.providers.support.pricing import margin_for_item, purchase_cost, selling_rate

WAREHOUSES = "erpnext.catalog.warehouses"
ITEM_GROUPS = "erpnext.catalog.item_groups"
PRICE_LISTS = "erpnext.catalog.price_lists"
ITEMS = "erpnext.catalog.items"


class ErpnextCatalogProvider(ScenarioProvider):
	id = "erpnext.catalog"
	version = "0.1.0"
	title = "ERPNext Catalog"
	description = "Warehouses, item groups, items, price lists, and cost-derived selling prices."
	role = "provider"
	app = "frappe_scenario"
	order = 50

	requires_apps = {"erpnext": ">=15.0.0"}
	requires_capabilities = {COMPANY, ACCOUNTS}
	provides_capabilities = {WAREHOUSES, ITEM_GROUPS, PRICE_LISTS, ITEMS}

	capabilities = [
		CapabilityDeclaration(
			id=WAREHOUSES,
			description="Scenario warehouses described by company.warehouses.",
			doctypes=["Warehouse"],
			requires=[COMPANY],
		),
		CapabilityDeclaration(
			id=ITEM_GROUPS,
			description="Item groups for each archetype item family.",
			doctypes=["Item Group"],
			requires=[COMPANY],
		),
		CapabilityDeclaration(
			id=PRICE_LISTS,
			description="Scenario-owned buying and selling price lists in the scenario currency.",
			doctypes=["Price List"],
			requires=[COMPANY],
		),
		CapabilityDeclaration(
			id=ITEMS,
			description=(
				"Items priced from purchase cost plus the family's gross margin, with buying "
				"and selling Item Prices."
			),
			doctypes=["UOM", "Item", "Item Price"],
			requires=[ITEM_GROUPS, PRICE_LISTS, WAREHOUSES],
			validation_rules=[
				"erpnext.catalog.item_count",
				"erpnext.catalog.selling_above_cost",
				"erpnext.catalog.margin_band",
				"erpnext.catalog.kind_margin_order",
			],
		),
	]

	def get_options_schema(self) -> dict[str, Any]:
		return {
			"type": "object",
			"additionalProperties": False,
			"properties": {
				"buying_price_list": {"type": "string"},
				"selling_price_list": {"type": "string"},
			},
		}

	# -- planning ------------------------------------------------------------
	def plan(self, context: ScenarioContext) -> ScenarioPlan:
		families = context.archetype.selected_families(context.specification)
		item_count = int(context.section("catalog").get("item_count") or 0)
		warehouses = context.section("company").get("warehouses") or []

		plan = ScenarioPlan(provider=self.id)
		plan.step(
			WAREHOUSES, f"Create {len(warehouses)} warehouses.", doctype="Warehouse", count=len(warehouses)
		)
		plan.step(
			ITEM_GROUPS,
			f"Create item groups for {len(families)} families.",
			doctype="Item Group",
			count=len({family.item_group for family in families}),
		)
		plan.step(PRICE_LISTS, "Create buying and selling price lists.", doctype="Price List", count=2)
		plan.step(
			ITEMS,
			f"Create {item_count} items with buying and selling prices.",
			doctype="Item",
			count=item_count * 3,
		)

		if item_count < len(families):
			plan.assumptions.append(
				f"item_count ({item_count}) is below the number of selected families "
				f"({len(families)}); one family per commercial kind is prioritised."
			)
		plan.assumptions.append(
			"Selling rates are derived as cost divided by one minus the family gross margin."
		)
		return plan

	# -- generation ----------------------------------------------------------
	def generate(self, context: ScenarioContext) -> ProviderResult:
		result = ProviderResult(provider=self.id)
		company = context.require(COMPANY)

		warehouses = self._create_warehouses(context, company)
		context.publish(WAREHOUSES, warehouses)
		result.published.append(WAREHOUSES)

		item_groups = self._create_item_groups(context)
		context.publish(ITEM_GROUPS, item_groups)
		result.published.append(ITEM_GROUPS)

		price_lists = self._create_price_lists(context)
		context.publish(PRICE_LISTS, price_lists)
		result.published.append(PRICE_LISTS)

		items = self._create_items(context, company, warehouses, item_groups, price_lists)
		context.publish(ITEMS, items)
		result.published.append(ITEMS)

		result.summary = {"items": len(items), "warehouses": len(warehouses["all"])}
		return result

	# -- warehouses ----------------------------------------------------------
	def _create_warehouses(self, context: ScenarioContext, company: str) -> dict[str, Any]:
		context.current_capability = WAREHOUSES
		root = tools.warehouse_root(company)
		if not root:
			raise ProviderError(
				"The company has no warehouse tree; ERPNext should have created one.",
				provider=self.id,
				capability=WAREHOUSES,
				phase="generate",
			)

		abbr = tools.company_abbr(company)
		created: dict[str, str] = {}
		for entry in context.section("company").get("warehouses") or []:
			title = entry.get("title") or entry["type"].replace("_", " ").title()
			full_name = f"{title} - {abbr}"
			if frappe.db.exists("Warehouse", full_name):
				created[entry["type"]] = full_name
				continue
			doc = context.insert(
				{
					"doctype": "Warehouse",
					"warehouse_name": title,
					"parent_warehouse": root,
					"company": company,
					"is_group": 0,
				},
				capability=WAREHOUSES,
				logical_id=f"warehouse:{entry['type']}",
			)
			created[entry["type"]] = doc.name

		default = (
			created.get("main_store")
			or next(iter(created.values()), None)
			or tools.default_warehouse(company)
		)
		if not default:
			raise ProviderError(
				"No usable warehouse could be resolved for the company.",
				provider=self.id,
				capability=WAREHOUSES,
				phase="generate",
			)
		return {"default": default, "by_type": created, "all": sorted(set(created.values()) | {default})}

	# -- item groups ---------------------------------------------------------
	def _create_item_groups(self, context: ScenarioContext) -> dict[str, str]:
		context.current_capability = ITEM_GROUPS
		root = (
			frappe.db.get_value("Item Group", {"is_group": 1, "parent_item_group": ""}, "name")
			or "All Item Groups"
		)

		groups: dict[str, str] = {}
		for family in context.archetype.selected_families(context.specification):
			if family.item_group in groups:
				continue
			if frappe.db.exists("Item Group", family.item_group):
				groups[family.item_group] = family.item_group
				continue
			doc = context.insert(
				{
					"doctype": "Item Group",
					"item_group_name": family.item_group,
					"parent_item_group": root,
					"is_group": 0,
				},
				capability=ITEM_GROUPS,
				logical_id=f"item_group:{family.item_group}",
			)
			groups[family.item_group] = doc.name
		return groups

	# -- price lists ---------------------------------------------------------
	def _create_price_lists(self, context: ScenarioContext) -> dict[str, str]:
		context.current_capability = PRICE_LISTS
		options = self.options(context)
		currency = context.currency

		buying = options.get("buying_price_list") or f"Scenario Buying {currency}"
		selling = options.get("selling_price_list") or f"Scenario Selling {currency}"

		for name, is_buying in ((buying, True), (selling, False)):
			if frappe.db.exists("Price List", name):
				continue
			context.insert(
				{
					"doctype": "Price List",
					"price_list_name": name,
					"currency": currency,
					"buying": 1 if is_buying else 0,
					"selling": 0 if is_buying else 1,
					"enabled": 1,
				},
				capability=PRICE_LISTS,
				logical_id=f"price_list:{'buying' if is_buying else 'selling'}",
			)
		return {"buying": buying, "selling": selling}

	# -- items ---------------------------------------------------------------
	def _create_items(
		self,
		context: ScenarioContext,
		company: str,
		warehouses: dict[str, Any],
		item_groups: dict[str, str],
		price_lists: dict[str, str],
	) -> list[dict[str, Any]]:
		context.current_capability = ITEMS
		random = context.random("items")
		pack = context.country_pack
		archetype = context.archetype
		precision = pack.currency_precision

		families = archetype.selected_families(context.specification)
		counts = _allocate_items(random, families, int(context.section("catalog").get("item_count") or 0))

		self._ensure_uoms(context, families)

		items: list[dict[str, Any]] = []
		sequence = 0
		for family in families:
			for _ in range(counts.get(family.key, 0)):
				sequence += 1
				cost = purchase_cost(random, family, pack.price_scale, precision)
				margin = margin_for_item(random, archetype, family, context.specification)
				rate = selling_rate(cost, margin, precision)
				code = item_code(family, sequence)
				name = item_name(random, family)[:140]

				doc = context.insert(
					{
						"doctype": "Item",
						"item_code": code,
						"item_name": name,
						"item_group": item_groups[family.item_group],
						"stock_uom": family.uom,
						"is_stock_item": 1 if family.is_stock_item else 0,
						"is_purchase_item": 1,
						"is_sales_item": 1,
						"include_item_in_manufacturing": 0,
						"lead_time_days": random.randint(*family.lead_time_days)
						if family.lead_time_days[1]
						else 0,
						"description": item_description(family, name),
						"item_defaults": [
							{
								"company": company,
								"default_warehouse": warehouses["default"] if family.is_stock_item else None,
							}
						],
					},
					capability=ITEMS,
					logical_id=f"item:{code}",
				)

				self._create_item_price(context, doc.name, price_lists["buying"], cost, buying=True)
				self._create_item_price(context, doc.name, price_lists["selling"], rate, buying=False)

				items.append(
					{
						"item_code": doc.name,
						"family": family.key,
						"kind": family.kind,
						"item_group": family.item_group,
						"uom": family.uom,
						"is_stock_item": family.is_stock_item,
						"cost": cost,
						"rate": rate,
						"margin": margin,
						"quantity_range": list(family.quantity_range),
						"lead_time_days": list(family.lead_time_days),
						"demand_weight": family.demand_weight,
					}
				)
				context.progress(f"Created item {doc.name}.", current=sequence)

		if not items:
			raise ProviderError(
				"The catalog produced no items; check catalog.item_count and catalog.families.",
				provider=self.id,
				capability=ITEMS,
				phase="generate",
			)
		return items

	def _ensure_uoms(self, context: ScenarioContext, families: list[ItemFamily]) -> None:
		for uom in sorted({family.uom for family in families}):
			if frappe.db.exists("UOM", uom):
				continue
			context.insert(
				{"doctype": "UOM", "uom_name": uom, "enabled": 1},
				capability=ITEMS,
				logical_id=f"uom:{uom}",
			)

	def _create_item_price(
		self, context: ScenarioContext, item: str, price_list: str, rate: float, *, buying: bool
	) -> None:
		context.insert(
			{
				"doctype": "Item Price",
				"item_code": item,
				"price_list": price_list,
				"price_list_rate": rate,
				"currency": context.currency,
				"buying": 1 if buying else 0,
				"selling": 0 if buying else 1,
			},
			capability=ITEMS,
			dependencies=[f"Item/{item}", f"Price List/{price_list}"],
		)

	# -- validation ----------------------------------------------------------
	def validate(self, context: ScenarioContext) -> ValidationResult:
		result = ValidationResult()
		items = context.optional(ITEMS) or []
		spec_validation = context.section("validation")
		tolerance = float(spec_validation.get("margin_tolerance") or 0.02)
		allow_below_cost = bool(spec_validation.get("allow_below_cost_selling"))

		expected = int(context.section("catalog").get("item_count") or 0)
		if expected and len(items) != expected:
			result.warning(
				rule="erpnext.catalog.item_count",
				message=f"Requested {expected} items; the catalog holds {len(items)}.",
				provider=self.id,
				capability=ITEMS,
				observed=len(items),
				expected=expected,
			)

		archetype = context.archetype
		for item in items:
			family = archetype.family(item["family"])
			low, high = archetype.margin_range_for(family, context.specification)

			if item["rate"] < item["cost"] and not allow_below_cost:
				result.error(
					rule="erpnext.catalog.selling_above_cost",
					message=f"{item['item_code']} sells at {item['rate']} below its cost {item['cost']}.",
					provider=self.id,
					capability=ITEMS,
					doctype="Item",
					record=item["item_code"],
					observed=item["rate"],
					expected=f">= {item['cost']}",
					remediation="Set validation.allow_below_cost_selling if this is intended.",
				)

			if not (low - tolerance <= item["margin"] <= high + tolerance):
				result.warning(
					rule="erpnext.catalog.margin_band",
					message=(
						f"{item['item_code']} margin {item['margin']:.3f} is outside the "
						f"{family.key} band {low:.3f}-{high:.3f}."
					),
					provider=self.id,
					capability=ITEMS,
					doctype="Item",
					record=item["item_code"],
					observed=item["margin"],
					expected=[low, high],
				)

		self._validate_kind_order(context, items, result)
		return result

	def _validate_kind_order(
		self, context: ScenarioContext, items: list[dict[str, Any]], result: ValidationResult
	) -> None:
		"""Equipment must not be sold on wider margins than spares and services."""
		by_kind: dict[str, list[float]] = {}
		for item in items:
			by_kind.setdefault(item["kind"], []).append(item["margin"])

		def mean(kind: str) -> float | None:
			values = by_kind.get(kind)
			return sum(values) / len(values) if values else None

		equipment = mean("equipment")
		for richer in ("spare", "service"):
			value = mean(richer)
			if equipment is None or value is None:
				continue
			if equipment >= value:
				result.error(
					rule="erpnext.catalog.kind_margin_order",
					message=(
						f"Average equipment margin {equipment:.3f} is not below the average "
						f"{richer} margin {value:.3f}."
					),
					provider=self.id,
					capability=ITEMS,
					observed=equipment,
					expected=f"< {value:.3f}",
					remediation="Widen catalog.family_margin_overrides for spares and services.",
				)


def _allocate_items(random: Any, families: list[ItemFamily], item_count: int) -> dict[str, int]:
	"""Spread the catalog across families, keeping every commercial kind represented."""
	if item_count <= 0 or not families:
		return {}

	if item_count >= len(families):
		counts = {family.key: 1 for family in families}
		remaining = item_count - len(families)
		if remaining:
			extra = random.distribute(remaining, {family.key: family.catalog_weight for family in families})
			for key, value in extra.items():
				counts[key] += value
		return counts

	# Fewer items than families: one representative per commercial kind first,
	# then the heaviest remaining families.
	by_kind: dict[str, list[ItemFamily]] = {}
	for family in families:
		by_kind.setdefault(family.kind, []).append(family)

	chosen: list[ItemFamily] = []
	for kind in sorted(by_kind):
		best = sorted(by_kind[kind], key=lambda family: (-family.catalog_weight, family.key))[0]
		chosen.append(best)

	remainder = sorted(
		(family for family in families if family not in chosen),
		key=lambda family: (-family.catalog_weight, family.key),
	)
	chosen = (chosen + remainder)[:item_count]
	return {family.key: 1 for family in chosen}
