# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Shared Desk/CLI onboarding planning services."""

from __future__ import annotations

import json
from types import SimpleNamespace

import frappe
import pytest

from frappe_scenario.core import setup_wizard

pytestmark = pytest.mark.pure


@pytest.fixture(autouse=True)
def plain_frappe_errors(monkeypatch):
	monkeypatch.setattr(setup_wizard, "_", lambda message: message)

	def throw(message, exc=frappe.ValidationError, **kwargs):
		raise exc(message)

	monkeypatch.setattr(setup_wizard.frappe, "throw", throw)


def _report(*, company=True, setup=True, existing_records=0):
	companies = (
		[
			{
				"name": "Example Trading Company",
				"abbr": "ETC",
				"country": "Kuwait",
				"default_currency": "KWD",
				"enable_perpetual_inventory": 1,
			}
		]
		if company
		else []
	)
	return {
		"summary": {"blocking": 0},
		"findings": [],
		"erpnext": {"installed": True},
		"setup": {"complete": setup},
		"companies": companies,
		"global_defaults": {
			"company": "Example Trading Company" if company else None,
			"country": "Kuwait",
			"currency": "KWD",
			"language": "en",
			"timezone": "Asia/Kuwait",
		},
		"chart_of_accounts": {
			"by_company": {
				"Example Trading Company": {"total": 80} if company else {},
			}
		},
		"stock": {"valuation_method": "Moving Average"},
		"existing_business_data": {"total": existing_records},
	}


def test_defaults_cover_every_required_guided_choice():
	choices = setup_wizard.default_choices(_report())

	assert setup_wizard.validate_choices(choices) == choices
	assert choices["intent"] == "Quick Demo"
	assert choices["company_strategy"] == "initialize_if_needed"
	assert choices["history_months"] == 2
	assert "complexity" not in choices


def test_legacy_complexity_choice_migrates_to_operational_depth():
	choices = setup_wizard.default_choices(_report())
	choices.pop("depth")
	choices["complexity"] = "Complex Operations"

	resolved = setup_wizard.validate_choices(choices)

	assert resolved["depth"] == "Complex Operations"
	assert "complexity" not in resolved


def test_preview_reports_mutations_estimate_and_never_executes():
	report = _report(company=False)
	choices = setup_wizard.default_choices(report)

	proposal = setup_wizard.build_proposal(choices, report)

	assert proposal["approvable"]
	assert proposal["mutation_count"] > 0
	assert any(item["target"] == "Company" for item in proposal["mutations"])
	assert proposal["record_estimate"]["minimum"] < proposal["record_estimate"]["maximum"]
	assert proposal["executes_setup"] is False
	assert proposal["generates_data"] is False
	assert proposal["record_estimate"]["lifecycle"]["sales_orders"] > 0


@pytest.mark.parametrize("strategy", ["require_existing", "reuse_company"])
def test_existing_company_strategies_block_when_company_is_missing(strategy):
	report = _report(company=False)
	choices = setup_wizard.default_choices(report)
	choices["company_strategy"] = strategy

	proposal = setup_wizard.build_proposal(choices, report)

	assert not proposal["approvable"]
	assert any(item["key"] == "company_strategy" for item in proposal["blockers"])


def test_existing_chart_is_never_renumbered_by_bootstrap():
	report = _report()
	report["chart_of_accounts"]["by_company"]["Example Trading Company"] = {
		"total": 80,
		"numbered": 0,
		"unnumbered": 70,
	}
	choices = setup_wizard.default_choices(report)
	choices["account_numbering"] = "With Numbers"

	proposal = setup_wizard.build_proposal(choices, report)

	assert not proposal["approvable"]
	assert any(item["key"] == "chart_of_accounts.numbering" for item in proposal["blockers"])


def test_saving_choices_uses_versioned_onboarding_service_and_resets_approval(monkeypatch):
	report = _report()
	choices = setup_wizard.default_choices(report)
	doc = SimpleNamespace(status="Needs Scenario")
	captured = {}
	updated = SimpleNamespace(
		as_dict=lambda: {
			"state_version": 4,
			"setup_choices": json.dumps(choices),
			"preview": "{}",
			"progress": "{}",
			"errors": None,
			"last_preflight": "{}",
			"resolved_specification": None,
		}
	)
	monkeypatch.setattr(setup_wizard, "preflight_report", lambda: report)
	monkeypatch.setattr(setup_wizard.frappe, "get_single", lambda doctype: doc)

	def transition(target, **kwargs):
		captured.update({"target": target, **kwargs})
		return updated

	monkeypatch.setattr(setup_wizard, "transition_onboarding", transition)

	result = setup_wizard.save_choices(choices, expected_version=3)

	assert captured["target"] == "Needs Scenario"
	assert captured["expected_version"] == 3
	assert captured["updates"]["setup_approved"] == 0
	assert result["proposal"]["generates_data"] is False
	assert result["preview_is_saved"] is True


def test_approval_records_user_but_calls_no_setup_or_generation(monkeypatch):
	proposal = {
		"approvable": True,
		"mutations": [],
		"record_estimate": {"approximate": 100},
	}
	doc = SimpleNamespace(status="Needs Setup", preview=json.dumps(proposal))
	captured = {}
	updated = SimpleNamespace(
		as_dict=lambda: {
			"state_version": 5,
			"setup_choices": "{}",
			"preview": json.dumps(proposal),
			"progress": "{}",
			"errors": None,
			"last_preflight": "{}",
			"resolved_specification": None,
		}
	)
	monkeypatch.setattr(setup_wizard.frappe, "get_single", lambda doctype: doc)
	monkeypatch.setattr(
		setup_wizard.frappe,
		"session",
		SimpleNamespace(user="administrator@example.test"),
	)
	monkeypatch.setattr(setup_wizard, "now_datetime", lambda: "2026-07-31 11:00:00")

	def transition(target, **kwargs):
		captured.update({"target": target, **kwargs})
		return updated

	monkeypatch.setattr(setup_wizard, "transition_onboarding", transition)

	setup_wizard.approve_setup(expected_version=4)

	assert captured["expected_version"] == 4
	assert captured["updates"]["setup_approved"] == 1
	assert captured["updates"]["setup_approved_by"] == "administrator@example.test"
