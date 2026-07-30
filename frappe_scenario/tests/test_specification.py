# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Specification loading, schema validation, and default resolution."""

import copy

import pytest

from frappe_scenario.core.errors import ScenarioError
from frappe_scenario.core.specification import (
	load_specification,
	problems_as_html,
	resolve_specification,
	validate_schema,
)

pytestmark = pytest.mark.pure

MINIMAL = {
	"schema_version": "1.0",
	"title": "Smoke",
	"scenario": {"archetype": "hvac_distribution", "country": "Kuwait", "scale": "smoke", "seed": 7},
}


def test_a_minimal_specification_satisfies_the_schema():
	assert validate_schema(copy.deepcopy(MINIMAL)) == []


def test_the_archetype_is_required():
	problems = validate_schema({"schema_version": "1.0", "scenario": {}})
	assert any(problem["path"] == "/scenario" for problem in problems)


def test_an_unknown_scenario_key_is_rejected():
	"""``scenario`` is closed, so a misplaced key is reported rather than ignored."""
	spec = copy.deepcopy(MINIMAL)
	spec["scenario"]["title"] = "misplaced"
	assert validate_schema(spec)


def test_problems_carry_a_pointer_and_a_message():
	problems = validate_schema({"schema_version": "1.0", "scenario": {"archetype": 5}})
	assert problems
	for problem in problems:
		assert problem["severity"] == "error"
		assert problem["path"].startswith("/")
		assert problem["message"]


def test_yaml_and_json_load_to_the_same_specification():
	as_json = load_specification('{"schema_version": "1.0", "scenario": {"archetype": "hvac_distribution"}}')
	as_yaml = load_specification("schema_version: '1.0'\nscenario:\n  archetype: hvac_distribution\n")
	assert as_json == as_yaml


def test_a_malformed_document_is_rejected_rather_than_guessed_at():
	with pytest.raises((ScenarioError, ValueError)):
		load_specification("{not: valid: json")


def test_resolution_fills_defaults_and_explains_every_one():
	resolved, assumptions = resolve_specification(copy.deepcopy(MINIMAL))

	assert resolved["scenario"]["archetype"] == "hvac_distribution"
	assert assumptions
	for assumption in assumptions:
		assert assumption["path"].startswith("/")
		assert assumption["reason"]


def test_resolution_never_overwrites_an_explicit_choice():
	spec = copy.deepcopy(MINIMAL)
	spec["scenario"]["currency"] = "USD"
	resolved, _ = resolve_specification(spec)
	assert resolved["scenario"]["currency"] == "USD"


def test_resolution_is_idempotent():
	once, _ = resolve_specification(copy.deepcopy(MINIMAL))
	twice, _ = resolve_specification(copy.deepcopy(once))
	assert twice == once


def test_resolution_rejects_a_specification_that_fails_the_schema():
	with pytest.raises(ScenarioError):
		resolve_specification({"schema_version": "1.0", "scenario": {}})


def test_problem_rendering_escapes_the_offending_value():
	html = problems_as_html([{"path": "/scenario", "message": "<script>alert(1)</script>"}])
	assert "<script>" not in html
	assert "&lt;script&gt;" in html
