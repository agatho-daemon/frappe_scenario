# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""ERPNext onboarding bootstrap safety and ownership tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

import frappe
import pytest

from frappe_scenario.core import bootstrap

pytestmark = pytest.mark.pure


@pytest.fixture(autouse=True)
def plain_frappe_errors(monkeypatch):
	monkeypatch.setattr(bootstrap, "_", lambda message: message)

	def throw(message, exc=frappe.ValidationError, **kwargs):
		raise exc(message)

	monkeypatch.setattr(bootstrap.frappe, "throw", throw)


def _choices(strategy="initialize_if_needed"):
	return {
		"company_strategy": strategy,
		"company_name": "Example Trading Company",
		"perpetual_inventory": True,
		"valuation_method": "Moving Average",
	}


def _report(*, existing_data=0, default_company="Example Trading Company"):
	return {
		"erpnext": {"installed": True},
		"companies": [
			{
				"name": "Example Trading Company",
				"enable_perpetual_inventory": 1,
			}
		],
		"global_defaults": {"company": default_company},
		"stock": {"valuation_method": "Moving Average"},
		"existing_business_data": {"total": existing_data},
	}


def test_bootstrap_requires_explicit_approval(monkeypatch):
	doc = SimpleNamespace(state_version=3, bootstrap_completed=0, setup_approved=0)
	monkeypatch.setattr(bootstrap.frappe, "get_single", lambda doctype: doc)

	with pytest.raises(frappe.ValidationError, match="Approve"):
		bootstrap.execute_approved_bootstrap(expected_version=3)


def test_completed_bootstrap_is_idempotent(monkeypatch):
	doc = SimpleNamespace(
		state_version=4,
		bootstrap_completed=1,
		setup_approved=1,
		setup_choices="{}",
		preview="{}",
		progress="{}",
		errors=None,
		last_preflight="{}",
		bootstrap_manifest='{"records": []}',
		as_dict=lambda: {
			"state_version": 4,
			"bootstrap_completed": 1,
			"bootstrap_manifest": '{"records": []}',
		},
	)
	monkeypatch.setattr(bootstrap.frappe, "get_single", lambda doctype: doc)

	result = bootstrap.execute_approved_bootstrap(expected_version=4)

	assert result["changed"] is False
	assert result["generates_data"] is False


def test_reuse_refuses_ambiguous_existing_business_data():
	choices = _choices("reuse_company")
	report = _report(existing_data=12, default_company="Another Company")

	with pytest.raises(frappe.ValidationError, match="ambiguous reuse"):
		bootstrap._validate_execution(choices, report, {"blockers": [], "mutations": []})


def test_bootstrap_refuses_when_site_changed_after_approval(monkeypatch):
	doc = SimpleNamespace(
		state_version=3,
		bootstrap_completed=0,
		setup_approved=1,
		setup_choices="{}",
		preview='{"mutations": [{"field": "country", "current": null}]}',
	)
	monkeypatch.setattr(bootstrap.frappe, "get_single", lambda doctype: doc)
	monkeypatch.setattr(bootstrap, "validate_choices", lambda value: value)
	monkeypatch.setattr(bootstrap, "preflight_report", _report)
	monkeypatch.setattr(
		bootstrap,
		"build_proposal",
		lambda choices, report: {"blockers": [], "mutations": []},
	)

	with pytest.raises(frappe.TimestampMismatchError, match="changed after approval"):
		bootstrap.execute_approved_bootstrap(expected_version=3)


def test_setting_changes_record_original_values_only_once():
	class FakeDoc:
		doctype = "Stock Settings"
		name = "Stock Settings"
		docstatus = 0

		def __init__(self):
			self.values = {"valuation_method": "FIFO"}
			self.saves = 0

		def get(self, field):
			return self.values.get(field)

		def update(self, values):
			self.values.update(values)

		def save(self, **kwargs):
			self.saves += 1

	doc = FakeDoc()
	manifest = bootstrap.Manifest()

	bootstrap._set_fields(doc, {"valuation_method": "Moving Average"}, manifest)
	bootstrap._set_fields(doc, {"valuation_method": "Moving Average"}, manifest)

	assert doc.saves == 1
	assert len(manifest.modified()) == 1
	assert manifest.modified()[0].original_values == {"valuation_method": "FIFO"}


def test_successful_bootstrap_persists_manifest_and_advances_state(monkeypatch):
	choices = _choices()
	doc = SimpleNamespace(
		state_version=7,
		bootstrap_completed=0,
		setup_approved=1,
		setup_choices=json.dumps(choices),
		preview='{"mutations": []}',
		bootstrap_manifest=None,
	)
	updated = SimpleNamespace(
		as_dict=lambda: {
			"state_version": 8,
			"bootstrap_completed": 1,
			"setup_choices": json.dumps(choices),
			"preview": "{}",
			"progress": "{}",
			"errors": None,
			"last_preflight": "{}",
			"bootstrap_manifest": '{"records": []}',
		}
	)
	captured = {}
	report = _report()
	monkeypatch.setattr(bootstrap.frappe, "get_single", lambda doctype: doc)
	monkeypatch.setattr(bootstrap, "validate_choices", lambda value: value)
	monkeypatch.setattr(bootstrap, "preflight_report", lambda: report)
	monkeypatch.setattr(bootstrap, "now_datetime", lambda: "2026-07-31 09:30:00")
	monkeypatch.setattr(
		bootstrap,
		"build_proposal",
		lambda choices, report: {"blockers": [], "mutations": []},
	)
	for helper, result in (
		("_settings_snapshot", {}),
		("_install_master_fixtures_if_needed", None),
		("_ensure_company", "Example Trading Company"),
		("_ensure_fiscal_year", "2026"),
		("_ensure_warehouse", "Stores - ETC"),
		("_ensure_cost_center", "Main - ETC"),
		("_record_planned_setting_changes", None),
		("_align_settings", None),
		("_mark_setup_complete", None),
	):
		monkeypatch.setattr(bootstrap, helper, lambda *args, _result=result: _result)
	monkeypatch.setattr(
		bootstrap.frappe,
		"db",
		SimpleNamespace(savepoint=lambda name: None, rollback=lambda **kwargs: None),
	)

	def transition(target, **kwargs):
		captured.update({"target": target, **kwargs})
		return updated

	monkeypatch.setattr(bootstrap, "transition_onboarding", transition)

	result = bootstrap.execute_approved_bootstrap(expected_version=7)

	assert result["changed"] is True
	assert captured["target"] == bootstrap.NEEDS_SCENARIO
	assert captured["updates"]["bootstrap_completed"] == 1
	assert captured["updates"]["bootstrap_manifest"]["version"] == "1.0"
	assert result["generates_data"] is False
