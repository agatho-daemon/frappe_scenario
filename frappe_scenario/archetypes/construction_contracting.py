# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Construction contracting archetype contract, hidden until project providers ship."""

from frappe_scenario.archetypes.base import Archetype, ItemFamily

ARCHETYPE = Archetype(
	id="construction_contracting",
	title="Construction and Project Contracting",
	description="A project contractor managing tenders, materials, subcontract work, progress billing, and retention.",
	default_country="Kuwait",
	industry="Construction",
	item_groups=["Project Materials", "Site Services", "Contract Milestones"],
	warehouses=[
		{"type": "main_store", "title": "Central Store"},
		{"type": "project_site", "title": "Project Site Store"},
	],
	families=[
		ItemFamily(
			"project_materials",
			"Project Materials",
			"consumable",
			"Project Materials",
			"Nos",
			(5, 500),
			(0.12, 0.25),
			(14, 75),
			descriptors=("Approved", "Commercial", "Heavy Duty"),
		),
		ItemFamily(
			"site_services",
			"Site Services",
			"service",
			"Site Services",
			"Day",
			(40, 350),
			(0.25, 0.48),
			(0, 0),
			is_stock_item=False,
			descriptors=("Installation", "Supervision", "Testing"),
		),
		ItemFamily(
			"contract_milestones",
			"Contract Milestones",
			"service",
			"Contract Milestones",
			"Nos",
			(500, 15000),
			(0.18, 0.35),
			(0, 0),
			is_stock_item=False,
			descriptors=("Mobilization", "Progress", "Handover"),
		),
	],
	customer_segments={"private_developer": 3, "main_contractor": 4, "government_entity": 2},
	payment_terms={"net_30": 3, "net_60": 4, "net_90": 2},
	peak_months=[10, 11, 12, 1, 2, 3],
	peak_multiplier=1.25,
	cash_sales_ratio=0,
	gross_margin_range=(0.12, 0.48),
	uoms=["Nos", "Meter", "Day", "Hour"],
	supported_modules=("CRM", "Selling", "Buying", "Stock", "Projects", "Accounts"),
	operational_ratios={"returns": 0.02, "customer_concentration": 0.55},
	learning_paths=("crm-parties", "buying", "projects", "stock", "selling", "payments"),
	validation_expectations=("balanced_books", "project_links", "progress_billing", "retention_balance"),
	required_capabilities=("erpnext.projects.contracts", "erpnext.projects.progress_billing"),
	lifecycle_validated=False,
	unavailable_reason="Requires optional project-contracting and progress-billing providers.",
)
