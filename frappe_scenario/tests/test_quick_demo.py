# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Quick Demo compilation and onboarding execution."""

from __future__ import annotations

import datetime
import json
from types import SimpleNamespace

import pytest

from frappe_scenario.core import quick_demo
from frappe_scenario.core.specification import validate_schema

pytestmark = pytest.mark.pure


def _choices() -> dict:
	return {
		"intent": "Quick Demo",
		"archetype": "hvac_distribution",
		"depth": "Everyday Business",
		"company_strategy": "initialize_if_needed",
		"country": "Kuwait",
		"language": "en",
		"timezone": "Asia/Kuwait",
		"currency": "KWD",
		"company_name": "Wasaq Climate Solutions",
		"company_abbr": "WCS",
		"chart_template": "Standard",
		"account_numbering": "With Numbers",
		"fiscal_year_start": "2026-01-01",
		"perpetual_inventory": 1,
		"valuation_method": "Moving Average",
		"warehouse_name": "Main Stores",
		"cost_center_name": "Main",
		"scale": "small",
		"history_months": 2,
		"preview_variation": 0,
	}


def test_quick_demo_compilation_is_deterministic_and_requests_the_full_lifecycle():
	anchor = datetime.date(2026, 7, 31)

	first = quick_demo.compile_quick_demo_specification(_choices(), anchor_date=anchor)
	second = quick_demo.compile_quick_demo_specification(_choices(), anchor_date=anchor)

	assert first == second
	assert validate_schema(first) == []
	assert first["company"]["industry"] == "Distribution"
	assert first["operations"]["partial_deliveries"] > 0
	assert first["operations"]["returns"] > 0
	assert set(first["providers"]) == {
		"frappe.foundation",
		"erpnext.foundation",
		"erpnext.parties",
		"erpnext.catalog",
		"erpnext.opening",
		"erpnext.buying",
		"erpnext.selling",
		"erpnext.payments",
	}


def test_quick_demo_changes_seed_when_the_anchor_changes():
	first = quick_demo.compile_quick_demo_specification(
		_choices(), anchor_date=datetime.date(2026, 7, 30)
	)
	second = quick_demo.compile_quick_demo_specification(
		_choices(), anchor_date=datetime.date(2026, 7, 31)
	)

	assert first["scenario"]["seed"] != second["scenario"]["seed"]


def test_quick_demo_execution_uses_the_approved_engine_path(monkeypatch):
	choices = _choices()
	start = SimpleNamespace(
		state_version=4,
		bootstrap_completed=1,
		scenario_run=None,
		setup_choices=json.dumps(choices),
	)
	preview = SimpleNamespace(state_version=5)
	generating = SimpleNamespace(state_version=6)
	ready = SimpleNamespace(
		state_version=7,
		as_dict=lambda: {
			"state_version": 7,
			"setup_choices": json.dumps(choices),
			"preview": "{}",
			"progress": "{}",
			"errors": None,
			"last_preflight": "{}",
			"bootstrap_manifest": "{}",
			"resolved_specification": "{}",
		},
	)
	transitions = iter([preview, generating, ready])
	calls: list[tuple[str, object]] = []
	monkeypatch.setattr(quick_demo.frappe, "get_single", lambda doctype: start)
	monkeypatch.setattr(
		quick_demo.engine,
		"plan",
		lambda specification, **kwargs: {
			"blocked": False,
			"specification": specification,
		},
	)
	monkeypatch.setattr(
		quick_demo.engine,
		"create_run",
		lambda specification, title=None: calls.append(("create", title)) or "SCN-RUN-1",
	)
	monkeypatch.setattr(
		quick_demo.engine,
		"approve_run",
		lambda name: calls.append(("approve", name)),
	)
	monkeypatch.setattr(
		quick_demo.engine,
		"execute_run",
		lambda name, **kwargs: calls.append(("execute", name))
		or {"run_id": name, "status": quick_demo.engine.STATUS_COMPLETED},
	)
	monkeypatch.setattr(
		quick_demo,
		"transition_onboarding",
		lambda *args, **kwargs: next(transitions),
	)

	result = quick_demo.generate_quick_demo(expected_version=4)

	assert result["created"] is True
	assert calls == [
		("create", "Wasaq Climate Solutions — Quick Demo"),
		("approve", "SCN-RUN-1"),
		("execute", "SCN-RUN-1"),
	]


def test_quick_demo_requires_quick_demo_intent(monkeypatch):
	choices = _choices()
	choices["intent"] = "Learn ERPNext"
	doc = SimpleNamespace(
		state_version=2,
		bootstrap_completed=1,
		scenario_run=None,
		setup_choices=json.dumps(choices),
	)
	monkeypatch.setattr(quick_demo.frappe, "get_single", lambda doctype: doc)
	monkeypatch.setattr(quick_demo, "_", lambda message: message)
	monkeypatch.setattr(
		quick_demo.frappe,
		"throw",
		lambda message, *args, **kwargs: (_ for _ in ()).throw(ValueError(message)),
	)

	with pytest.raises(ValueError, match="requires the Quick Demo purpose"):
		quick_demo.generate_quick_demo(expected_version=2)
