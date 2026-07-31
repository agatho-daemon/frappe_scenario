# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Site-backed contract for onboarding persistence.

This test is transactional and creates no ERPNext business data.
"""

import json

import pytest

from frappe_scenario.core.onboarding import DOCTYPE, STATES, ensure_onboarding

pytestmark = pytest.mark.frappe_site


def test_onboarding_singleton_initializes_without_business_data(frappe_site, rollback):
	import frappe

	before = {
		doctype: frappe.db.count(doctype)
		for doctype in ("Company", "Customer", "Supplier", "Item", "Sales Invoice")
		if frappe.db.exists("DocType", doctype)
	}
	report = {
		"summary": {"blocking": 0},
		"erpnext": {"installed": True},
		"setup": {"complete": True},
		"companies": [{"name": "Existing Company"}],
		"findings": [],
	}
	doc = frappe.get_single(DOCTYPE)
	doc.initialized_on = None
	doc.status = "Needs Prerequisites"
	doc.state_version = 0
	doc.initial_route_pending = 1
	doc.save(ignore_permissions=True)

	initialized = ensure_onboarding(report=report)

	assert initialized.status in STATES
	assert initialized.state_version == 1
	assert json.loads(initialized.last_preflight) == report
	assert {doctype: frappe.db.count(doctype) for doctype in before} == before


def test_builtin_learning_paths_are_synchronized(frappe_site):
	import frappe

	from frappe_scenario.core.learning_catalog import PATHS

	assert frappe.db.count("Scenario Learning Path", {"enabled": 1}) == len(PATHS)


def test_troubleshooting_metadata_is_installed(frappe_site):
	import frappe

	assert frappe.db.table_exists("Scenario Lab Case")
