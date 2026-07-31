# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Learning catalogue safety and coverage."""

from __future__ import annotations

import pytest

from frappe_scenario.core.learning import VERIFIERS
from frappe_scenario.core.learning_catalog import GLOSSARY, PATHS, flatten_steps

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
			assert step["verifier"] in VERIFIERS
			serialized = repr(step).lower()
			assert "eval" not in serialized
			assert "python" not in serialized
			assert "javascript" not in serialized
			assert "selector" not in serialized


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
