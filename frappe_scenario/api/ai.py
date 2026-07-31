# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Read-only AI adapter discovery APIs."""

from __future__ import annotations

from typing import Any

import frappe

from frappe_scenario.ai.configuration import parse_public_configuration
from frappe_scenario.ai.registry import discover_ai_adapters

ROLE = "System Manager"
PROVIDER_DOCTYPE = "Scenario AI Provider"


@frappe.whitelist(methods=["POST"])
def compile_brief(
	brief: str,
	constraints: str | dict[str, Any] | None = None,
	provider: str = "openai",
	model: str | None = None,
	title: str | None = None,
) -> dict[str, Any]:
	"""Compile a brief through an enabled adapter and create a review draft."""
	frappe.only_for(ROLE)
	from frappe_scenario.ai.compilation import compile_ai_brief

	parsed_constraints = (
		frappe.parse_json(constraints) if isinstance(constraints, str) else (constraints or {})
	)
	if not isinstance(parsed_constraints, dict):
		frappe.throw("Constraints must be a JSON object.")
	return compile_ai_brief(
		brief,
		constraints=parsed_constraints,
		provider=provider,
		model=model,
		title=title,
	)


@frappe.whitelist(methods=["POST"])
def review_onboarding_preview(
	provider: str = "openai",
	model: str | None = None,
) -> dict[str, Any]:
	"""Review only qualitative artifacts from the saved onboarding preview."""
	frappe.only_for(ROLE)
	from frappe_scenario.ai.plausibility import review_onboarding_preview as review

	return review(provider=provider, model=model)


@frappe.whitelist(methods=["POST"])
def approve_plausibility_review(review: str) -> dict[str, Any]:
	"""Approve cached textual suggestions without mutating ERPNext records."""
	frappe.only_for(ROLE)
	from frappe_scenario.ai.plausibility import approve_review

	return approve_review(review)


@frappe.whitelist(methods=["POST"])
def reject_plausibility_review(review: str) -> dict[str, Any]:
	frappe.only_for(ROLE)
	from frappe_scenario.ai.plausibility import reject_review

	return reject_review(review)


@frappe.whitelist()
def get_approved_plausibility_artifacts(review: str) -> dict[str, Any]:
	frappe.only_for(ROLE)
	from frappe_scenario.ai.plausibility import approved_artifacts

	return approved_artifacts(review)


@frappe.whitelist(methods=["POST"])
def ask_scenario_tutor(
	run_name: str,
	question: str,
	provider: str = "openai",
	model: str | None = None,
) -> dict[str, Any]:
	"""Ask a read-only question grounded in one Scenario Run's evidence."""
	frappe.only_for(ROLE)
	from frappe_scenario.ai.tutor import ask_tutor

	return ask_tutor(run_name, question, provider=provider, model=model)


@frappe.whitelist(methods=["POST"])
def confirm_tutor_corrections(exchange: str) -> dict[str, Any]:
	"""Confirm suggestions for audit only; no corrective action is executed."""
	frappe.only_for(ROLE)
	from frappe_scenario.ai.tutor import confirm_corrections

	return confirm_corrections(exchange)


@frappe.whitelist()
def describe_ai_adapters() -> dict[str, Any]:
	"""Return capabilities and safe configuration status, never credentials."""
	frappe.only_for(ROLE)
	registry = discover_ai_adapters()
	configured = {
		row.provider: row
		for row in frappe.get_all(
			PROVIDER_DOCTYPE,
			fields=["name", "provider", "enabled", "model", "configuration"],
		)
	}
	items = []
	for adapter in registry.adapters:
		row = configured.get(adapter.id)
		public_config = parse_public_configuration(row.configuration if row else None)
		if row and row.model:
			public_config["model"] = row.model
		credential_present = bool(
			row
			and frappe.get_doc(PROVIDER_DOCTYPE, row.name).get_password("credential", raise_exception=False)
		)
		status = adapter.validate_configuration(
			configured=credential_present,
			configuration=public_config,
		)
		items.append(
			{
				**adapter.describe(),
				"enabled": bool(row and row.enabled),
				"configuration": status.as_dict(),
			}
		)
	return {
		"adapters": items,
		"external_agent": {
			"available": True,
			"compile_api": "frappe_scenario.api.agent.compile_brief",
			"submit_api": "frappe_scenario.api.agent.submit_draft",
		},
	}
