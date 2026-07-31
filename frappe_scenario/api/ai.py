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
