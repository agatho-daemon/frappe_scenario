# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Declarative archetype contracts and their publication gate."""

import pytest

from frappe_scenario.archetypes import describe_archetypes, get_archetype, list_archetypes
from frappe_scenario.core.errors import SpecificationError
from frappe_scenario.core.specification import resolve_specification

pytestmark = pytest.mark.pure


def test_only_lifecycle_validated_archetypes_are_advertised():
	ready = set(list_archetypes())
	all_archetypes = {entry["id"]: entry for entry in describe_archetypes(include_unavailable=True)}

	assert {"distribution_wholesale", "retail", "professional_services"} <= ready
	assert "manufacturing" not in ready
	assert "construction_contracting" not in ready
	assert all(all_archetypes[key]["lifecycle_validated"] for key in ready)
	assert all_archetypes["manufacturing"]["unavailable_reason"]


@pytest.mark.parametrize("archetype_id", list_archetypes())
def test_every_advertised_archetype_declares_its_acceptance_contract(archetype_id):
	archetype = get_archetype(archetype_id)

	assert archetype.supported_modules
	assert archetype.families
	assert archetype.customer_segments
	assert archetype.operational_ratios
	assert archetype.learning_paths
	assert archetype.validation_expectations
	assert archetype.required_capabilities


@pytest.mark.parametrize("archetype_id", ["manufacturing", "construction_contracting"])
def test_an_unaccepted_archetype_cannot_be_resolved(archetype_id):
	with pytest.raises(SpecificationError, match="not available"):
		resolve_specification(
			{"schema_version": "1.0", "scenario": {"archetype": archetype_id, "scale": "smoke"}}
		)


@pytest.mark.parametrize("archetype_id", ["distribution_wholesale", "retail", "professional_services"])
def test_new_ready_archetypes_resolve_with_their_vocabulary_and_ratios(archetype_id):
	resolved, _ = resolve_specification(
		{"schema_version": "1.0", "scenario": {"archetype": archetype_id, "scale": "smoke"}}
	)
	archetype = get_archetype(archetype_id)

	assert resolved["catalog"]["families"] == [family.key for family in archetype.families]
	for key, value in archetype.operational_ratios.items():
		assert resolved["operations"][key] == value
