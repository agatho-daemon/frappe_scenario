# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Framework foundation provider.

Aligns the site's global conventions with the scenario: country, date format,
number precision, and the first day of the working week.

These are pre-existing singletons, not scenario-owned records, so every change is
recorded with its original value and restored on cleanup.
"""

from __future__ import annotations

from typing import Any

import frappe

from frappe_scenario.core.context import ScenarioContext
from frappe_scenario.core.provider import (
	CapabilityDeclaration,
	ProviderResult,
	ScenarioPlan,
	ScenarioProvider,
)
from frappe_scenario.core.validation import ValidationResult

CAPABILITY = "frappe.foundation.settings"

SYSTEM_SETTINGS_FIELDS = (
	"country",
	"date_format",
	"float_precision",
	"currency_precision",
	"first_day_of_the_week",
)


class FrappeFoundationProvider(ScenarioProvider):
	id = "frappe.foundation"
	version = "0.1.0"
	title = "Framework Foundation"
	description = "Aligns site-wide conventions with the scenario's country and currency."
	role = "provider"
	app = "frappe_scenario"
	order = 10

	provides_capabilities = {CAPABILITY}

	capabilities = [
		CapabilityDeclaration(
			id=CAPABILITY,
			description=(
				"Sets System Settings and Global Defaults to the scenario country, currency, "
				"and working week, and enables the scenario currency."
			),
			doctypes=["System Settings", "Global Defaults", "Currency"],
			estimated_records="0 created, 3 modified",
			safety=(
				"Modifies pre-existing singletons. Original values are recorded and restored on cleanup."
			),
			validation_rules=["frappe.settings.currency_enabled"],
		)
	]

	def get_options_schema(self) -> dict[str, Any]:
		return {
			"type": "object",
			"additionalProperties": False,
			"properties": {
				"align_system_settings": {
					"type": "boolean",
					"description": "Set System Settings to the scenario conventions.",
				},
				"align_global_defaults": {
					"type": "boolean",
					"description": "Set the site default currency and country.",
				},
			},
		}

	# -- planning ------------------------------------------------------------
	def plan(self, context: ScenarioContext) -> ScenarioPlan:
		pack = context.country_pack
		plan = ScenarioPlan(provider=self.id)
		plan.step(CAPABILITY, f"Enable currency {context.currency}.", doctype="Currency")
		plan.step(
			CAPABILITY,
			(
				f"Set System Settings to country {pack.country}, currency precision "
				f"{pack.currency_precision}, first day of week {pack.first_day_of_week}."
			),
			doctype="System Settings",
		)
		plan.step(
			CAPABILITY,
			f"Set the site default currency to {context.currency}.",
			doctype="Global Defaults",
		)
		plan.settings_changed.extend(
			[
				"System Settings: country, date_format, float_precision, currency_precision, "
				"first_day_of_the_week",
				"Global Defaults: default_currency, country",
				f"Currency {context.currency}: enabled",
			]
		)
		plan.cleanup_notes.append(
			"Cleanup restores the recorded original values of System Settings, Global Defaults, "
			"and the currency's enabled flag."
		)
		return plan

	# -- generation ----------------------------------------------------------
	def generate(self, context: ScenarioContext) -> ProviderResult:
		options = self.options(context)
		pack = context.country_pack
		result = ProviderResult(provider=self.id)
		context.current_capability = CAPABILITY

		result.modified += self._enable_currency(context)

		if options.get("align_system_settings", True):
			result.modified += self._align_single(
				context,
				"System Settings",
				{
					"country": pack.country,
					"date_format": "dd-mm-yyyy",
					"float_precision": "6",
					"currency_precision": str(pack.currency_precision),
					"first_day_of_the_week": pack.first_day_of_week,
				},
			)

		if options.get("align_global_defaults", True):
			result.modified += self._align_single(
				context,
				"Global Defaults",
				{"default_currency": context.currency, "country": pack.country},
			)

		context.publish(
			CAPABILITY,
			{
				"country": pack.country,
				"currency": context.currency,
				"currency_precision": pack.currency_precision,
				"first_day_of_week": pack.first_day_of_week,
				"weekend_days": list(pack.weekend_days),
			},
		)
		result.published.append(CAPABILITY)
		return result

	def _enable_currency(self, context: ScenarioContext) -> int:
		currency = context.currency
		if not frappe.db.exists("Currency", currency):
			doc = context.insert(
				{
					"doctype": "Currency",
					"currency_name": currency,
					"enabled": 1,
					"fraction_units": 1000 if context.country_pack.currency_precision == 3 else 100,
				},
				capability=CAPABILITY,
			)
			context.progress(f"Created currency {doc.name}.")
			return 0

		enabled = frappe.db.get_value("Currency", currency, "enabled")
		if enabled:
			return 0
		context.record_modified(
			frappe.get_doc("Currency", currency), {"enabled": enabled}, capability=CAPABILITY
		)
		frappe.db.set_value("Currency", currency, "enabled", 1, update_modified=False)
		return 1

	def _align_single(self, context: ScenarioContext, doctype: str, values: dict[str, Any]) -> int:
		doc = frappe.get_single(doctype)
		original = {field: doc.get(field) for field in values if doc.get(field) != values[field]}
		if not original:
			return 0

		context.record_modified(doc, original, capability=CAPABILITY)
		for field, value in values.items():
			if field in original:
				frappe.db.set_single_value(doctype, field, value)
		frappe.clear_document_cache(doctype, doctype)
		context.progress(f"Aligned {doctype}: {', '.join(sorted(original))}.")
		return 1

	# -- validation ----------------------------------------------------------
	def validate(self, context: ScenarioContext) -> ValidationResult:
		result = ValidationResult()
		if not frappe.db.get_value("Currency", context.currency, "enabled"):
			result.error(
				rule="frappe.settings.currency_enabled",
				message=f"Currency {context.currency} is not enabled.",
				provider=self.id,
				capability=CAPABILITY,
				doctype="Currency",
				record=context.currency,
				remediation=f"Enable the {context.currency} Currency record.",
			)
		return result
