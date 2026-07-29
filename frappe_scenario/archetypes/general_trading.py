# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""General trading archetype.

A deliberately plain business used by the pure-core test suite and as the
neutral starting point when a brief does not describe a recognisable industry.
"""

from __future__ import annotations

from frappe_scenario.archetypes.base import Archetype, ItemFamily

FAMILIES = [
	ItemFamily(
		key="goods",
		title="Traded Goods",
		item_group="Traded Goods",
		kind="equipment",
		uom="Nos",
		cost_range=(10.0, 400.0),
		margin_range=(0.15, 0.28),
		lead_time_days=(14, 45),
		catalog_weight=3.0,
		demand_weight=3.0,
		quantity_range=(1, 20),
		descriptors=("Standard", "Premium", "Economy", "Bulk"),
	),
	ItemFamily(
		key="consumables",
		title="Consumables",
		item_group="Consumables",
		kind="consumable",
		uom="Nos",
		cost_range=(2.0, 40.0),
		margin_range=(0.28, 0.45),
		lead_time_days=(7, 21),
		catalog_weight=2.0,
		demand_weight=2.5,
		quantity_range=(5, 100),
		descriptors=("Refill", "Pack", "Cartridge", "Roll"),
	),
	ItemFamily(
		key="services",
		title="Services",
		item_group="Services",
		kind="service",
		uom="Nos",
		cost_range=(20.0, 250.0),
		margin_range=(0.45, 0.65),
		lead_time_days=(0, 0),
		catalog_weight=0.8,
		demand_weight=1.2,
		is_stock_item=False,
		quantity_range=(1, 10),
		descriptors=("Installation", "Support", "Training", "Consulting"),
	),
]

ARCHETYPE = Archetype(
	id="general_trading",
	title="General Trading",
	description="A small trading company buying and reselling goods with a light service line.",
	default_country="United States",
	industry="Distribution",
	item_groups=["Traded Goods", "Consumables", "Services"],
	warehouses=[{"type": "main_store", "title": "Main Store"}],
	families=FAMILIES,
	customer_segments={"wholesale": 3.0, "retail": 2.0},
	payment_terms={"cash": 2.0, "net_30": 3.0, "net_60": 1.0},
	peak_months=[11, 12],
	peak_multiplier=1.25,
	cash_sales_ratio=0.3,
	gross_margin_range=(0.15, 0.65),
	uoms=["Nos", "Box", "Hour"],
)
