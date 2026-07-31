# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""The full lifecycle against a disposable ERPNext site.

These tests write real documents through normal controllers and then remove them
again. They are the only place the promises in the README are actually proven:
that a run validates, that the same seed reproduces the same dataset, and that
cleanup gives the site back.
"""

import datetime

import pytest

from frappe_scenario.core.canonical import canonical_projection
from frappe_scenario.core.engine import (
	cleanup_run,
	create_run,
	execute_run,
	export_run,
	load_manifest,
	plan,
	validate_run,
)

pytestmark = pytest.mark.erpnext_site


def _first_difference(left, right, path="$"):
	if type(left) is not type(right):
		return f"{path}: type {type(left).__name__} != {type(right).__name__}"
	if isinstance(left, dict):
		if left.keys() != right.keys():
			return f"{path}: keys {sorted(left)} != {sorted(right)}"
		for key in left:
			if difference := _first_difference(left[key], right[key], f"{path}.{key}"):
				return difference
	elif isinstance(left, list):
		if len(left) != len(right):
			return f"{path}: length {len(left)} != {len(right)}"
		for index, (left_item, right_item) in enumerate(zip(left, right, strict=True)):
			if difference := _first_difference(left_item, right_item, f"{path}[{index}]"):
				return difference
	elif left != right:
		return f"{path}: {left!r} != {right!r}"
	return None


def _generate(specification: dict) -> dict:
	run_name = create_run(specification, approved=True)
	result = execute_run(run_name)
	assert result["status"] == "Completed", result.get("error")
	return result


@pytest.fixture(scope="module")
def generated(erpnext_site, smoke_specification):
	"""One generated scenario, cleaned up when the module is done.

	Generation commits, so this cannot be wrapped in a savepoint. The fixture
	owns the cleanup instead, and asserts that cleanup itself is complete.
	Cleaning an already-cleaned run is a no-op, so a test is free to clean this
	run early.
	"""
	result = _generate(smoke_specification)
	yield result
	cleanup = cleanup_run(result["run_id"])
	assert cleanup["blockers"] == []
	assert cleanup["status"] == "Cleaned Up"


def test_a_plan_describes_the_work_without_writing_anything(erpnext_site, smoke_specification):
	import frappe

	before = frappe.db.count("Company")
	described = plan(smoke_specification)

	assert not described["blocked"]
	assert described["estimated_records"] > 0
	assert described["execution_order"][0] == "frappe.foundation"
	assert described["specification_hash"]
	assert described["assumptions"]
	assert frappe.db.count("Company") == before


def test_a_plan_explains_every_default_it_applied(erpnext_site, smoke_specification):
	for assumption in plan(smoke_specification)["assumptions"]:
		assert assumption["path"].startswith("/")
		assert assumption["reason"]


def test_a_plan_warns_about_what_cleanup_will_not_restore(erpnext_site, smoke_specification):
	described = plan(smoke_specification)
	assert described["cleanup_notes"]
	assert described["settings_changed"]


def test_a_generated_scenario_records_everything_it_created(generated):
	manifest = load_manifest(generated["run_id"])

	# The reported count is of created records. The manifest also carries the
	# settings a run changed, which cleanup restores rather than deletes.
	assert len(manifest.created()) == generated["record_count"]
	assert len(manifest) > len(manifest.created())
	assert generated["canonical_hash"]
	assert generated["structural_hash"]


def test_every_manifest_record_actually_exists(generated):
	import frappe

	manifest = load_manifest(generated["run_id"])
	missing = [
		record.reference for record in manifest.created() if not frappe.db.exists(record.doctype, record.name)
	]
	assert missing == []


def test_the_generated_scenario_validates(generated):
	import frappe

	result = validate_run(generated["run_id"])
	assert result["counts"]["error"] == 0, result["issues"]
	assert result["passed"]
	assert result["quality"]["passed"]
	assert set(result["quality"]["scores"]) == {
		"naming",
		"regional_consistency",
		"linkage",
		"accounting",
		"continuity",
	}
	assert frappe.db.exists("Scenario Quality Report", result["quality"]["name"])


def test_quick_demo_exceptions_are_real_linked_erpnext_documents(generated):
	import frappe

	returns = frappe.get_all(
		"Sales Invoice",
		filters={"is_return": 1, "docstatus": 1},
		fields=["name", "return_against"],
	)
	assert returns
	assert all(row.return_against for row in returns)

	partial_deliveries = frappe.db.sql(
		"""
		select distinct dni.parent
		from `tabDelivery Note Item` dni
		join `tabSales Order Item` soi on soi.name = dni.so_detail
		where dni.docstatus = 1 and dni.qty < soi.qty
		""",
		as_dict=True,
	)
	assert partial_deliveries


def test_completed_run_exposes_report_ready_outcomes(generated):
	assert generated["outcomes"]["master_data"]["customers"] > 0
	assert generated["outcomes"]["selling"]["invoice_count"] > 0
	assert generated["outcomes"]["selling"]["return_documents"] > 0
	assert generated["outcomes"]["reports"]


def test_validation_findings_carry_enough_to_act_on(generated):
	for issue in validate_run(generated["run_id"])["issues"]:
		assert issue["rule"]
		assert issue["message"]
		assert issue["severity"] in {"error", "warning", "info"}


def test_the_books_balance(generated):
	"""Every posted voucher must net to zero, per company and per voucher."""
	import frappe
	from frappe.query_builder import DocType
	from frappe.query_builder.functions import Sum

	gl = DocType("GL Entry")
	rows = (
		frappe.qb.from_(gl)
		.select(gl.voucher_type, gl.voucher_no, Sum(gl.debit - gl.credit).as_("net"))
		.where(gl.is_cancelled == 0)
		.groupby(gl.voucher_type, gl.voucher_no)
		.run(as_dict=True)
	)
	assert rows
	unbalanced = [row for row in rows if abs(float(row.net or 0)) > 0.01]
	assert unbalanced == []


def test_stock_is_dated_no_later_than_the_anchor(generated, smoke_specification):
	import frappe

	anchor = smoke_specification["scenario"]["anchor_date"]
	later = frappe.get_all(
		"Stock Ledger Entry",
		filters={"posting_date": [">", anchor], "is_cancelled": 0},
		pluck="name",
	)
	assert later == []


def test_an_export_is_enough_to_reproduce_and_review_a_run(generated):
	exported = export_run(generated["run_id"])
	assert exported["specification"]
	assert exported["specification_hash"]
	assert exported["canonical_hash"] == generated["canonical_hash"]
	exported_at = datetime.datetime.fromisoformat(exported["exported_at"].replace("Z", "+00:00"))
	assert exported_at.tzinfo == datetime.UTC

	# A hash only means something alongside what produced it.
	assert exported["compatibility"]["compatibility"]["adapter"]
	assert exported["compatibility"]["installed_apps"]["erpnext"]
	assert exported["compatibility"]["provider_versions"]
	assert len(exported["manifest"]) >= generated["record_count"]


def test_the_same_seed_reproduces_the_same_dataset(erpnext_site, smoke_specification, generated):
	"""The headline promise, and the reason cleanup has to be complete.

	The second run can only match if the first one was removed without residue,
	so this exercises generation and cleanup together.
	"""
	first_projection = canonical_projection(load_manifest(generated["run_id"]))
	first_cleanup = cleanup_run(generated["run_id"])
	assert first_cleanup["blockers"] == []

	second = _generate(smoke_specification)
	try:
		second_projection = canonical_projection(load_manifest(second["run_id"]))
		assert second_projection == first_projection, _first_difference(first_projection, second_projection)
		assert second["canonical_hash"] == generated["canonical_hash"]
		assert second["record_count"] == generated["record_count"]
	finally:
		assert cleanup_run(second["run_id"])["blockers"] == []


@pytest.mark.parametrize("doctype", ["Company", "Customer", "Supplier", "Item", "GL Entry"])
def test_cleanup_leaves_nothing_behind(generated, doctype):
	"""Runs after the determinism test, by which point both runs are cleaned."""
	import frappe

	assert frappe.db.count(doctype) == 0
