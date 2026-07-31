# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Readiness assessment and dependency-contract tests."""

from __future__ import annotations

from types import SimpleNamespace

import frappe
import pytest

from frappe_scenario import hooks, install
from frappe_scenario.core import preflight


class ReadOnlyDatabase:
	def __init__(self, *, singles=None, counts=None, installed_application_table=True):
		self.singles = singles or {}
		self.counts = counts or {}
		self.installed_application_table = installed_application_table
		self.calls = []

	def get_single_value(self, doctype, field):
		self.calls.append(("get_single_value", doctype, field))
		return self.singles.get((doctype, field))

	def table_exists(self, table):
		self.calls.append(("table_exists", table))
		return self.installed_application_table

	def count(self, doctype, filters=None):
		self.calls.append(("count", doctype, filters))
		key = (doctype, _freeze(filters))
		return self.counts.get(key, self.counts.get(doctype, 0))


def _freeze(value):
	if isinstance(value, dict):
		return tuple(sorted((key, _freeze(item)) for key, item in value.items()))
	if isinstance(value, tuple):
		return tuple(_freeze(item) for item in value)
	return value


def _patch_site(monkeypatch, *, all_apps, installed_apps, rows=None, db=None, setup_complete=False):
	rows = rows or {}
	db = db or ReadOnlyDatabase()
	monkeypatch.setattr(preflight.frappe, "local", SimpleNamespace(site="example.local"))
	monkeypatch.setattr(preflight.frappe, "get_all_apps", lambda: list(all_apps))
	monkeypatch.setattr(preflight.frappe, "get_installed_apps", lambda: list(installed_apps))
	monkeypatch.setattr(preflight.frappe, "is_setup_complete", lambda: setup_complete)
	monkeypatch.setattr(preflight.frappe, "db", db)
	monkeypatch.setattr(
		preflight.frappe,
		"get_all",
		lambda doctype, **kwargs: rows.get(doctype, []),
	)
	monkeypatch.setattr(
		preflight,
		"site_safety_report",
		lambda: {
			"site": "example.local",
			"developer_mode": True,
			"disposable": True,
			"non_disposable_override_configured": False,
			"maintenance_mode": False,
			"generation_allowed": True,
		},
	)
	return db


@pytest.mark.pure
def test_erpnext_is_declared_as_an_installation_dependency():
	assert hooks.required_apps == ["erpnext"]


@pytest.mark.pure
def test_install_stops_with_exact_recovery_when_erpnext_checkout_is_absent(monkeypatch):
	monkeypatch.setattr(install.frappe, "get_all_apps", lambda: ["frappe", "frappe_scenario"])

	with pytest.raises(frappe.ValidationError) as raised:
		install.before_install()

	message = str(raised.value)
	for command in preflight.ERPNEXT_RECOVERY:
		assert command in message
	assert "does not fetch repositories" in message


@pytest.mark.pure
def test_absent_erpnext_checkout_is_blocking_and_gives_exact_recovery(monkeypatch):
	db = _patch_site(
		monkeypatch,
		all_apps={"frappe", "frappe_scenario"},
		installed_apps={"frappe", "frappe_scenario"},
	)

	report = preflight.preflight_report()

	assert report["status"] == preflight.BLOCKING
	assert report["erpnext"] == {
		"checkout_available": False,
		"installed": False,
		"recovery_commands": [
			"bench get-app erpnext",
			"bench install-app erpnext",
			"bench install-app frappe_scenario",
		],
	}
	assert not any(call[0] not in {"get_single_value"} for call in db.calls)


@pytest.mark.pure
def test_available_but_uninstalled_erpnext_is_configurable(monkeypatch):
	_patch_site(
		monkeypatch,
		all_apps={"frappe", "erpnext", "frappe_scenario"},
		installed_apps={"frappe", "frappe_scenario"},
	)

	report = preflight.preflight_report()

	assert report["status"] == preflight.CONFIGURABLE
	assert report["erpnext"]["checkout_available"]
	assert not report["erpnext"]["installed"]
	finding = next(item for item in report["findings"] if item["key"] == "erpnext.installed")
	assert finding["remediation"] == "bench install-app frappe_scenario"


@pytest.mark.pure
def test_configured_site_reports_setup_accounts_stock_and_existing_data(monkeypatch):
	companies = [
		frappe._dict(
			name="Acme Distribution",
			abbr="AD",
			country="Kuwait",
			default_currency="KWD",
			enable_perpetual_inventory=1,
			is_group=0,
		)
	]
	rows = {
		"Installed Application": [
			frappe._dict(app_name="frappe", is_setup_complete=1),
			frappe._dict(app_name="erpnext", is_setup_complete=1),
		],
		"Company": companies,
		"Fiscal Year": [
			frappe._dict(
				name="2026",
				year_start_date="2026-01-01",
				year_end_date="2026-12-31",
				disabled=0,
			)
		],
	}
	singles = {
		("System Settings", "country"): "Kuwait",
		("System Settings", "language"): "en",
		("System Settings", "time_zone"): "Asia/Kuwait",
		("Global Defaults", "default_company"): "Acme Distribution",
		("Global Defaults", "country"): "Kuwait",
		("Global Defaults", "default_currency"): "KWD",
		("Stock Settings", "valuation_method"): "Moving Average",
		("Stock Settings", "allow_negative_stock"): 0,
		("Stock Settings", "default_warehouse"): "Stores - AD",
		("Stock Settings", "stock_uom"): "Nos",
	}
	counts = {
		("Account", _freeze({"company": "Acme Distribution"})): 20,
		("Account", _freeze({"company": "Acme Distribution", "is_group": 1})): 8,
		(
			"Account",
			_freeze(
				{
					"company": "Acme Distribution",
					"is_group": 0,
					"account_number": ("is", "set"),
				}
			),
		): 12,
		"Customer": 2,
		"Sales Invoice": 1,
	}
	_patch_site(
		monkeypatch,
		all_apps={"frappe", "erpnext", "frappe_scenario"},
		installed_apps={"frappe", "erpnext", "frappe_scenario"},
		rows=rows,
		db=ReadOnlyDatabase(singles=singles, counts=counts),
		setup_complete=True,
	)

	report = preflight.preflight_report()

	assert report["setup"]["complete"]
	assert report["global_defaults"]["company"] == "Acme Distribution"
	assert report["chart_of_accounts"]["numbering_mode"] == "numbered"
	assert report["stock"]["valuation_method"] == "Moving Average"
	assert report["stock"]["companies"]["Acme Distribution"]["perpetual_inventory"]
	assert report["existing_business_data"]["total"] == 3
	assert report["status"] == preflight.DESTRUCTIVE_RISK
	assert report["summary"][preflight.DESTRUCTIVE_RISK] == 1


@pytest.mark.pure
def test_preflight_uses_only_read_operations(monkeypatch):
	db = _patch_site(
		monkeypatch,
		all_apps={"frappe", "erpnext", "frappe_scenario"},
		installed_apps={"frappe", "erpnext", "frappe_scenario"},
		db=ReadOnlyDatabase(),
	)

	preflight.preflight_report()

	assert {call[0] for call in db.calls} <= {"get_single_value", "table_exists", "count"}


@pytest.mark.frappe_site
def test_real_site_preflight_contract_is_read_only(frappe_site):
	report = preflight.preflight_report()

	assert report["site"] == frappe_site
	assert report["status"] in preflight.CLASSIFICATIONS
	assert set(report["summary"]) == set(preflight.CLASSIFICATIONS)
	assert report["environment"]["versions"]["frappe"]["installed_on_site"]
	assert all(finding["classification"] in preflight.CLASSIFICATIONS for finding in report["findings"])
