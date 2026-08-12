# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Learning catalogue safety and coverage."""

from __future__ import annotations

import pytest
from frappe import ValidationError

from frappe_scenario.core.learning import VERIFIERS
from frappe_scenario.core.learning_catalog import (
	GLOSSARY,
	PATHS,
	STEP_TYPES,
	flatten_steps,
	lesson_versions,
	step_contract,
)
from frappe_scenario.core.learning_portal import (
	LEARNER_ROLES,
	MODULE_DOCTYPES,
	MODULE_ROLES,
	PATH_PREREQUISITES,
)
from frappe_scenario.core.learning_verifiers import verify_named
from frappe_scenario.core.tutorial_runner import (
	ALLOWED_ACTIONS,
	LESSON_KEY,
	PATH_KEY,
	SEMANTIC_TARGET_KINDS,
)

pytestmark = pytest.mark.pure


def test_catalog_covers_the_planned_erpnext_learning_spectrum():
	assert [path["key"] for path in PATHS] == [
		"foundations",
		"crm-parties",
		"buying",
		"selling",
		"stock",
		"accounting",
		"returns",
		"reports",
		"period-closing",
	]
	assert all(path["lessons"] for path in PATHS)
	assert all(flatten_steps(path) for path in PATHS)


def test_every_step_uses_the_closed_server_verifier_vocabulary():
	for path in PATHS:
		for _, step in flatten_steps(path):
			assert step_contract(step)["verifier"] in VERIFIERS
			serialized = repr(step).lower()
			assert "eval" not in serialized
			assert "python" not in serialized
			assert "javascript" not in serialized
			assert "selector" not in serialized
			contract = step_contract(step)
			assert contract["step_type"] in STEP_TYPES
			assert contract["binding"].split(":", 1)[0] in {
				"event",
				"related",
				"scenario",
				"capability",
				"report",
				"doctype",
			}


def test_progressive_explanations_have_simple_and_advanced_glossary_text():
	referenced = {
		step["configuration"]["glossary"]
		for path in PATHS
		for _, step in flatten_steps(path)
		if step["configuration"].get("glossary")
	}
	assert referenced
	assert referenced <= set(GLOSSARY)
	assert all(GLOSSARY[term]["simple"] and GLOSSARY[term]["advanced"] for term in referenced)


def test_buying_and_selling_are_complete_multi_document_paths():
	by_key = {path["key"]: path for path in PATHS}
	for path_key, expected in {
		"buying": {"Purchase Order", "Purchase Receipt", "Purchase Invoice", "Supplier Payment"},
		"selling": {"Sales Order", "Delivery Note", "Sales Invoice", "Customer Payment"},
	}.items():
		events = {step["configuration"].get("event_type") for _, step in flatten_steps(by_key[path_key])}
		assert events == expected
		assert len(flatten_steps(by_key[path_key])) == 10
		assert lesson_versions(by_key[path_key])


def test_focused_selling_tutorial_has_ten_safe_scenario_bound_steps():
	path = next(path for path in PATHS if path["key"] == PATH_KEY)
	steps = [
		step
		for lesson_key, step in flatten_steps(path)
		if lesson_key == LESSON_KEY and step["configuration"].get("tutorial")
	]
	assert len(steps) == 10
	assert {step["configuration"]["tutorial"]["action"] for step in steps} <= ALLOWED_ACTIONS
	assert all(step_contract(step)["binding"].startswith("event:") for step in steps)
	assert all("selector" not in repr(step).lower() for step in steps)


def test_named_verifier_contract_contains_required_state_checks():
	assert {
		"document.exists",
		"document.submitted",
		"field.equals",
		"child_table.has_rows",
		"link.references",
		"invoice.outstanding_reduced",
		"stock.quantity_changed",
		"ledger.voucher_balanced",
		"report.contains_record",
	} <= set(VERIFIERS)
	assert SEMANTIC_TARGET_KINDS == {
		"doctype_field",
		"form_control",
		"registered_action",
		"workspace_shortcut",
		"report",
		"tutorial_hook",
		"document",
	}


def test_catalog_contract_cannot_carry_executable_or_client_locator_fields():
	for path in PATHS:
		for _, step in flatten_steps(path):
			configuration = step["configuration"]
			assert not ({"javascript", "python", "eval", "selector", "css"} & set(configuration))
			assert "css" not in repr(configuration).lower()
			assert set(step_contract(step)) == {"step_type", "binding", "fieldname", "verifier"}


def test_unknown_verifier_is_rejected_before_binding_resolution():
	with pytest.raises(ValidationError, match="Unsupported learning verifier"):
		verify_named(None, verifier="community.module.callable", binding="scenario:run")


def test_learning_roles_are_module_scoped_without_an_assignment_engine():
	assert "System Manager" in LEARNER_ROLES
	assert "Sales User" in MODULE_ROLES["Selling"]
	assert "Purchase User" in MODULE_ROLES["Buying"]
	assert "Stock User" in MODULE_ROLES["Stock"]
	assert "Accounts User" in MODULE_ROLES["Accounting"]
	assert "Sales User" not in MODULE_ROLES["Buying"]
	assert {"Sales Order", "Delivery Note", "Sales Invoice"} <= MODULE_DOCTYPES["Selling"]
	assert PATH_PREREQUISITES["returns"] == ("selling",)
