# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt

import pytest

from frappe_scenario.core.troubleshooting import AVAILABILITY, INJECTORS
from frappe_scenario.core.troubleshooting_catalog import PROBLEMS

pytestmark = pytest.mark.pure


def test_lab_catalog_covers_every_milestone_problem_family():
	assert {problem["key"] for problem in PROBLEMS} == {
		"unreconciled-payment",
		"overdue-account",
		"partial-delivery",
		"stock-shortage",
		"pricing-error",
		"credit-limit-breach",
		"posting-period",
	}


def test_lab_definitions_use_only_closed_injectors_and_diagnoses():
	for problem in PROBLEMS:
		assert problem["injector"] in INJECTORS
		assert problem["injector"] in AVAILABILITY
		choice_keys = {choice["key"] for choice in problem["choices"]}
		assert problem["accepted_diagnosis"] in choice_keys
		assert len(choice_keys) >= 3
		assert problem["hints"]
		definition = repr(problem).lower()
		assert "python" not in definition
		assert "eval(" not in definition
		assert "javascript" not in definition


def test_lab_does_not_publish_the_answer_in_its_public_problem_payload():
	from frappe_scenario.core.troubleshooting import _public_problem

	for problem in PROBLEMS:
		public = _public_problem(problem)
		assert "accepted_diagnosis" not in public
		assert "injector" not in public
