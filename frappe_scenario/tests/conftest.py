# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Site fixtures for the ``frappe_site`` and ``erpnext_site`` tiers.

The ``pure`` tier never touches these. A site tier is skipped rather than failed
when no site is named, so the whole suite stays runnable on a checkout with no
bench around it.

Point the site tiers at a disposable site::

        FRAPPE_SCENARIO_TEST_SITE=scenario15.local pytest -m erpnext_site
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

#: ``<bench>/apps/frappe_scenario/frappe_scenario/tests/conftest.py``
BENCH_ROOT = Path(__file__).resolve().parents[4]
SITES_PATH = BENCH_ROOT / "sites"


def _requested_site() -> str | None:
	return (os.environ.get("FRAPPE_SCENARIO_TEST_SITE") or "").strip() or None


@pytest.fixture(scope="session")
def frappe_site() -> str:
	"""A connected Frappe site, torn down without committing anything."""
	site = _requested_site()
	if not site:
		pytest.skip("Set FRAPPE_SCENARIO_TEST_SITE to a disposable site to run the site tiers.")
	if not SITES_PATH.is_dir():
		pytest.skip(f"No bench sites directory at {SITES_PATH}.")

	import frappe

	# Frappe resolves its log directory relative to the working directory, which
	# it assumes is the bench's ``sites`` folder. Without this the first log line
	# fails on a missing ``apps/logs`` path.
	previous_cwd = Path.cwd()
	os.chdir(SITES_PATH)

	frappe.init(site=site, sites_path=str(SITES_PATH))
	frappe.connect()
	frappe.set_user("Administrator")
	try:
		yield site
	finally:
		frappe.db.rollback()
		frappe.destroy()
		os.chdir(previous_cwd)


@pytest.fixture(scope="session")
def erpnext_site(frappe_site: str) -> str:
	"""A connected site that also has ERPNext installed."""
	import frappe

	if "erpnext" not in frappe.get_installed_apps():
		pytest.skip(f"ERPNext is not installed on {frappe_site}.")
	return frappe_site


@pytest.fixture
def rollback():
	"""Undo whatever a test wrote, without disturbing the wider transaction."""
	import frappe

	frappe.db.savepoint("frappe_scenario_test")
	try:
		yield
	finally:
		frappe.db.rollback(save_point="frappe_scenario_test")


@pytest.fixture(scope="session")
def smoke_specification() -> dict:
	"""The committed smoke example, so the tests exercise a shipped scenario."""
	from frappe_scenario.core.specification import read_specification_file

	path = Path(__file__).resolve().parents[2] / "examples" / "hvac_kuwait_smoke.json"
	specification = read_specification_file(str(path))
	specification["operations"] = {
		"partial_deliveries": 0.2,
		"returns": 0.15,
	}
	return specification
