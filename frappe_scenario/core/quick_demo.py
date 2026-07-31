# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Quick Demo preset compilation and onboarding execution."""

from __future__ import annotations

import datetime
import hashlib
import json
from typing import Any

import frappe
from frappe import _

from frappe_scenario.archetypes import get_archetype
from frappe_scenario.core import engine
from frappe_scenario.core.onboarding import (
	DOCTYPE,
	FAILED,
	GENERATING,
	PREVIEW,
	READY,
	transition_onboarding,
)
from frappe_scenario.core.setup_wizard import validate_choices
from frappe_scenario.locales import get_country_pack


def compile_quick_demo_specification(
	choices: dict[str, Any],
	*,
	anchor_date: datetime.date | None = None,
) -> dict[str, Any]:
	"""Compile approved onboarding choices into a versioned engine specification."""
	choices = validate_choices(choices)
	pack = get_country_pack(choices["country"])
	archetype = get_archetype(choices["archetype"])
	anchor = anchor_date or datetime.date.today()
	seed = _seed_for_choices(choices, anchor)
	return {
		"schema_version": "1.0",
		"title": f"{choices['company_name']} — Quick Demo",
		"scenario": {
			"intent": "Quick Demo",
			"archetype": choices["archetype"],
			"country": choices["country"],
			"locale": {
				"primary": pack.primary_locale,
				"secondary": pack.secondary_locale,
			},
			"currency": choices["currency"],
			"anchor_date": anchor.isoformat(),
			"history_months": choices["history_months"],
			"scale": choices["scale"],
			"depth": choices["depth"],
			"seed": seed,
		},
		"company": {
			"name": choices["company_name"],
			"abbr": choices["company_abbr"],
			"industry": archetype.industry,
			"enable_perpetual_inventory": choices["perpetual_inventory"],
		},
		"operations": {
			"partial_deliveries": 0.12,
			"returns": 0.08,
			"warranty_claims": 0,
		},
		"accounting": {
			"overdue_receivables": 0.18,
			"monthly_accruals": True,
			"year_end_adjustments": False,
		},
		"providers": {
			"frappe.foundation": {},
			"erpnext.foundation": {
				"chart_of_accounts": _chart_template(choices),
				"reuse_existing_company": True,
			},
			"erpnext.parties": {},
			"erpnext.catalog": {},
			"erpnext.opening": {"months_of_cover": 3},
			"erpnext.buying": {},
			"erpnext.selling": {},
			"erpnext.payments": {
				"partial_payment_ratio": 0.15,
			},
		},
	}


def generate_quick_demo(
	*,
	expected_version: int,
	allow_non_disposable: bool = False,
) -> dict[str, Any]:
	"""Create, approve, and synchronously execute one onboarding Quick Demo run."""
	doc = frappe.get_single(DOCTYPE)
	if int(doc.state_version or 0) != int(expected_version):
		frappe.throw(
			_("Onboarding changed in another session. Refresh and try again."),
			frappe.TimestampMismatchError,
		)
	if not doc.bootstrap_completed:
		frappe.throw(_("Initialize ERPNext foundations before generating a Quick Demo."))
	if doc.scenario_run:
		return {
			"onboarding": _serialize(doc),
			"run": engine.get_status(doc.scenario_run),
			"created": False,
		}

	choices = validate_choices(_decode(doc.setup_choices))
	if choices["intent"] != "Quick Demo":
		frappe.throw(_("The Quick Demo generator requires the Quick Demo purpose."))
	specification = compile_quick_demo_specification(choices)
	execution_plan = engine.plan(
		specification,
		allow_non_disposable=allow_non_disposable,
	)
	if execution_plan["blocked"]:
		frappe.throw(
			_(
				"Scenario generation is blocked on this site. Mark a learning site disposable "
				"or explicitly confirm non-disposable generation."
			),
			frappe.PermissionError,
		)

	preview_doc = transition_onboarding(
		PREVIEW,
		expected_version=expected_version,
		updates={
			"resolved_specification": execution_plan["specification"],
			"progress": {
				"completed_steps": [
					"choices",
					"preview",
					"setup_approval",
					"erpnext_bootstrap",
					"scenario_preview",
				],
				"current_state": PREVIEW,
			},
		},
	)
	run_name = engine.create_run(
		execution_plan["specification"],
		title=specification["title"],
	)
	engine.approve_run(run_name)
	generating_doc = transition_onboarding(
		GENERATING,
		expected_version=int(preview_doc.state_version),
		updates={
			"scenario_run": run_name,
			"progress": {
				"completed_steps": [
					"choices",
					"preview",
					"setup_approval",
					"erpnext_bootstrap",
					"scenario_preview",
				],
				"current_state": GENERATING,
			},
		},
	)
	try:
		result = engine.execute_run(
			run_name,
			allow_non_disposable=allow_non_disposable,
		)
	except Exception as exception:
		transition_onboarding(
			FAILED,
			expected_version=int(generating_doc.state_version),
			updates={"errors": {"message": str(exception), "run_id": run_name}},
		)
		raise

	target = READY if result["status"] == engine.STATUS_COMPLETED else FAILED
	updated = transition_onboarding(
		target,
		expected_version=int(generating_doc.state_version),
		updates={
			"errors": result.get("error"),
			"progress": {
				"completed_steps": [
					"choices",
					"preview",
					"setup_approval",
					"erpnext_bootstrap",
					"scenario_preview",
					"quick_demo_generation",
				],
				"current_state": target,
			},
		},
	)
	return {
		"onboarding": _serialize(updated),
		"run": result,
		"created": True,
	}


def _chart_template(choices: dict[str, Any]) -> str:
	if choices["account_numbering"] == "With Numbers" and choices["chart_template"] == "Standard":
		return "Standard with Numbers"
	return choices["chart_template"]


def _seed_for_choices(choices: dict[str, Any], anchor: datetime.date) -> int:
	material = {
		"choices": choices,
		"anchor_date": anchor.isoformat(),
		"preset": "quick-demo-1",
	}
	digest = hashlib.blake2b(
		json.dumps(material, sort_keys=True, default=str).encode("utf-8"),
		digest_size=4,
	).digest()
	return int.from_bytes(digest, "big")


def _decode(value: Any) -> dict[str, Any]:
	if isinstance(value, dict):
		return value
	if not value:
		return {}
	return json.loads(value)


def _serialize(doc: Any) -> dict[str, Any]:
	payload = doc.as_dict()
	for field in (
		"setup_choices",
		"preview",
		"progress",
		"errors",
		"last_preflight",
		"bootstrap_manifest",
		"resolved_specification",
	):
		payload[field] = _decode(payload.get(field))
	return payload
