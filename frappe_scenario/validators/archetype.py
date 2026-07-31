# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Acceptance contract for advertised business archetypes."""

from frappe_scenario.archetypes import get_archetype
from frappe_scenario.core.context import ScenarioContext
from frappe_scenario.core.validation import ValidationResult


def validate_archetype_contract(context: ScenarioContext) -> ValidationResult:
	result = ValidationResult()
	archetype = get_archetype(context.scenario["archetype"])
	missing = [
		capability for capability in archetype.required_capabilities if not context.optional(capability)
	]
	if missing:
		result.error(
			"archetype.required_capabilities",
			f"{archetype.title} did not produce required lifecycle capabilities: {missing}.",
			observed=missing,
			expected=list(archetype.required_capabilities),
			remediation="Do not advertise the archetype until every required provider lifecycle is complete.",
		)
	else:
		result.info(
			"archetype.acceptance",
			f"{archetype.title} produced its declared lifecycle capabilities.",
			expected=list(archetype.validation_expectations),
		)
	return result
