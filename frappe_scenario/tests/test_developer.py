# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Pure contracts for developer datasets and headless automation."""

from __future__ import annotations

import json

import pytest

from frappe_scenario import commands
from frappe_scenario.core import developer, engine
from frappe_scenario.core.errors import SafetyError, SpecificationError

pytestmark = pytest.mark.pure


@pytest.fixture
def base_specification():
	return {
		"schema_version": "1.0",
		"scenario": {"archetype": "hvac_distribution"},
		"operations": {"returns": 0.1},
		"providers": {"erpnext.selling": {"lines_per_order": [1, 4]}},
	}


def test_developer_compiler_exposes_deterministic_and_edge_case_controls(base_specification):
	compiled = developer.compile_developer_specification(
		base_specification,
		seed=429,
		scale="custom",
		anchor_date="2026-08-01",
		providers=["erpnext.selling", "erpnext.payments"],
		partial_delivery_ratio=0.75,
		return_ratio=0.4,
		overdue_ratio=0.6,
		skip_rules=["erpnext.payments.overdue_profile"],
		sets=["/catalog/item_count=37", "/accounting/monthly_accruals=true"],
		available_providers={"erpnext.selling", "erpnext.payments"},
	)

	assert compiled["scenario"] == {
		"archetype": "hvac_distribution",
		"intent": "Developer/Test Dataset",
		"seed": 429,
		"scale": "custom",
		"anchor_date": "2026-08-01",
	}
	assert compiled["operations"]["partial_deliveries"] == 0.75
	assert compiled["operations"]["returns"] == 0.4
	assert compiled["accounting"]["overdue_receivables"] == 0.6
	assert compiled["accounting"]["monthly_accruals"] is True
	assert compiled["catalog"]["item_count"] == 37
	assert list(compiled["providers"]) == ["erpnext.selling", "erpnext.payments"]
	assert compiled["provider_selection"] == ["erpnext.selling", "erpnext.payments"]
	assert compiled["providers"]["erpnext.selling"] == {"lines_per_order": [1, 4]}
	assert compiled["validation"]["skip_rules"] == ["erpnext.payments.overdue_profile"]
	assert base_specification["scenario"] == {"archetype": "hvac_distribution"}


@pytest.mark.parametrize(
	"assignment",
	["not-a-pointer", "/catalog/item_count=not-json", "=1", "/=1"],
)
def test_advanced_overrides_reject_ambiguous_or_executable_input(base_specification, assignment):
	with pytest.raises(SpecificationError):
		developer.compile_developer_specification(base_specification, sets=[assignment])


def test_provider_selection_rejects_unknown_capabilities(base_specification):
	with pytest.raises(SpecificationError) as caught:
		developer.compile_developer_specification(
			base_specification,
			providers=["invented.provider"],
			available_providers={"erpnext.selling"},
		)
	assert caught.value.details["unknown"] == ["invented.provider"]


def test_engine_never_silently_ignores_an_unknown_provider():
	class Registry:
		def __contains__(self, provider_id):
			return provider_id == "known.provider"

	with pytest.raises(SpecificationError, match="not available"):
		engine._requested_providers({"providers": {"invented.provider": {}}}, Registry())


def test_automation_envelope_and_exit_codes_are_stable(monkeypatch, base_specification):
	monkeypatch.setattr(engine, "plan", lambda *args, **kwargs: {"blocked": False, "planned": True})
	payload, exit_code = developer.automate("plan", base_specification)
	assert exit_code == developer.EXIT_SUCCESS
	assert payload == {
		"format": "frappe-scenario-automation-1",
		"operation": "plan",
		"ok": True,
		"exit_code": 0,
		"data": {"blocked": False, "planned": True},
		"error": None,
	}

	monkeypatch.setattr(
		engine,
		"plan",
		lambda *args, **kwargs: {"blocked": True, "safety": {"blockers": ["not disposable"]}},
	)
	payload, exit_code = developer.automate("generate", base_specification)
	assert exit_code == developer.EXIT_SAFETY == 20
	assert payload["error"]["code"] == "safety_error"


def test_validation_and_cleanup_have_distinct_machine_exit_codes(monkeypatch):
	monkeypatch.setattr(
		engine,
		"validate_run",
		lambda run: {"run_id": run, "passed": False, "counts": {"error": 1}},
	)
	payload, exit_code = developer.automate("validate", "SCN-RUN-1")
	assert (payload["ok"], exit_code) == (False, developer.EXIT_VALIDATION)

	monkeypatch.setattr(
		engine,
		"cleanup_run",
		lambda run, **kwargs: {"run_id": run, "blockers": [{"message": "external link"}]},
	)
	payload, exit_code = developer.automate("cleanup", "SCN-RUN-1")
	assert (payload["ok"], exit_code) == (False, developer.EXIT_CLEANUP)


def test_json_artifact_writer_is_deterministic(tmp_path):
	output = tmp_path / "result.json"
	encoded = developer.write_json({"z": 1, "a": 2}, str(output))
	assert output.read_text(encoding="utf-8") == encoded
	assert list(json.loads(encoded)) == ["a", "z"]


def test_developer_command_is_registered_with_all_headless_operations():
	command = commands.scenario.commands["developer"]
	assert [choice for choice in command.params[0].type.choices] == [
		"plan",
		"generate",
		"validate",
		"export",
		"cleanup",
	]
