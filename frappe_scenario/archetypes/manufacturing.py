# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Manufacturing archetype contract, hidden until its optional provider ships."""

from frappe_scenario.archetypes.base import Archetype, ItemFamily

ARCHETYPE = Archetype(
	id="manufacturing",
	title="Manufacturing",
	description="A make-to-stock manufacturer with materials, finished goods, production, and quality control.",
	default_country="United States",
	industry="Manufacturing",
	item_groups=["Raw Materials", "Finished Goods", "Manufacturing Services"],
	warehouses=[
		{"type": "raw_material", "title": "Raw Materials"},
		{"type": "work_in_progress", "title": "Work In Progress"},
		{"type": "finished_goods", "title": "Finished Goods"},
	],
	families=[
		ItemFamily(
			"raw_materials",
			"Raw Materials",
			"consumable",
			"Raw Materials",
			"Kg",
			(2, 80),
			(0.08, 0.16),
			(14, 60),
			descriptors=("Industrial", "Standard", "Certified"),
		),
		ItemFamily(
			"finished_goods",
			"Finished Goods",
			"equipment",
			"Finished Goods",
			"Nos",
			(40, 900),
			(0.18, 0.34),
			(0, 0),
			descriptors=("Standard", "Professional", "Heavy Duty"),
		),
		ItemFamily(
			"production_services",
			"Production Services",
			"service",
			"Manufacturing Services",
			"Hour",
			(20, 120),
			(0.35, 0.55),
			(0, 0),
			is_stock_item=False,
			descriptors=("Assembly", "Calibration", "Commissioning"),
		),
	],
	customer_segments={"distributor": 4, "original_equipment_manufacturer": 2, "project_buyer": 2},
	payment_terms={"net_30": 4, "net_60": 3, "net_90": 1},
	peak_months=[3, 9, 10],
	peak_multiplier=1.2,
	cash_sales_ratio=0.02,
	gross_margin_range=(0.08, 0.55),
	uoms=["Nos", "Kg", "Meter", "Hour"],
	supported_modules=("CRM", "Selling", "Buying", "Stock", "Manufacturing", "Quality", "Accounts"),
	operational_ratios={"returns": 0.03},
	learning_paths=("crm-parties", "buying", "manufacturing", "stock", "selling", "payments"),
	validation_expectations=("balanced_books", "stock_integrity", "bom_yield", "work_order_links"),
	required_capabilities=("erpnext.manufacturing.work_orders", "erpnext.manufacturing.stock_entries"),
	lifecycle_validated=False,
	unavailable_reason="Requires the optional manufacturing lifecycle provider and its acceptance suite.",
)
