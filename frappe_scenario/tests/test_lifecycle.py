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

from frappe_scenario.archetypes import get_archetype
from frappe_scenario.core import engine
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
from frappe_scenario.core.experimentation import (
	create_checkpoint,
	describe_changes,
	reset_module,
	restore_scenario,
)
from frappe_scenario.core.learning import learning_home, verify_step
from frappe_scenario.core.narrative import explain_record
from frappe_scenario.core.scale import get_scale_profile
from frappe_scenario.core.troubleshooting import (
	activate_problem,
	check_diagnosis,
	lab_home,
	restore_case,
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


def test_cancel_rollback_and_resume_at_provider_boundaries(erpnext_site, smoke_specification, monkeypatch):
	"""A committed phase can be inspected, removed, retried, and completed."""
	run_name = create_run(smoke_specification, approved=True)
	checks = 0

	def cancel_after_first_checkpoint(_run_name):
		nonlocal checks
		checks += 1
		return checks >= 2

	monkeypatch.setattr(engine, "_cancellation_requested", cancel_after_first_checkpoint)
	cancelled = execute_run(run_name)
	assert cancelled["status"] == "Cancelled"
	status = engine.get_status(run_name)
	assert status["progress"] == {
		"completed_phases": 1,
		"total_phases": len(status["steps"]),
		"current_phase": None,
	}
	assert status["steps"][0]["input_fingerprint"]
	assert status["steps"][0]["output_fingerprint"]

	rolled_back = engine.rollback_last_phase(run_name)
	assert rolled_back["rolled_back"]
	assert rolled_back["result"]["blockers"] == []

	# Restore the real database-backed cancellation check before resuming.
	monkeypatch.undo()
	completed = engine.resume_run(run_name)
	assert completed["status"] == "Completed", completed.get("error")
	status = engine.get_status(run_name)
	assert status["progress"]["completed_phases"] == status["progress"]["total_phases"]
	assert all(step["input_fingerprint"] and step["output_fingerprint"] for step in status["steps"])

	cleanup = cleanup_run(run_name)
	assert cleanup["status"] == "Cleaned Up"
	assert cleanup["blockers"] == []


def test_a_queued_run_cancels_before_any_provider_starts(erpnext_site, smoke_specification):
	import frappe

	run_name = create_run(smoke_specification, approved=True)
	frappe.db.set_value("Scenario Run", run_name, "status", "Queued", update_modified=False)
	frappe.db.commit()

	assert engine.request_cancellation(run_name)["status"] == "Cancelled"
	assert execute_run(run_name)["status"] == "Cancelled"
	assert load_manifest(run_name).records == []
	assert cleanup_run(run_name)["status"] == "Cleaned Up"


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


@pytest.mark.parametrize("scale,history,confirmation", [("medium", 24, False), ("large", 36, True)])
def test_realistic_scale_plans_match_their_volume_contract(erpnext_site, scale, history, confirmation):
	described = plan(
		{
			"schema_version": "1.0",
			"scenario": {
				"archetype": "hvac_distribution",
				"country": "Kuwait",
				"scale": scale,
				"anchor_date": "2026-07-31",
				"seed": 17,
			},
		}
	)
	target = get_scale_profile(scale)["record_target"]
	assert described["specification"]["scenario"]["history_months"] == history
	assert target["minimum"] <= described["estimated_records"] <= target["maximum"]
	assert described["resource_estimate"]["database_rows"] > described["estimated_records"]
	assert described["confirmation_required"] is confirmation
	assert described["resource_estimate"]["lifecycle"]["customer_payments"] > 0


@pytest.mark.parametrize(
	("archetype_id", "seed"),
	[
		("general_trading", 101),
		("distribution_wholesale", 102),
		("retail", 103),
		("professional_services", 104),
	],
)
def test_every_newly_advertised_archetype_passes_its_real_lifecycle(erpnext_site, archetype_id, seed):
	import json

	import frappe

	archetype = get_archetype(archetype_id)
	run_name = create_run(
		{
			"schema_version": "1.0",
			"scenario": {
				"archetype": archetype_id,
				"scale": "smoke",
				"anchor_date": "2026-01-31",
				"seed": seed,
			},
		},
		approved=True,
	)
	try:
		generated = execute_run(run_name)
		assert generated["status"] == "Completed", generated.get("error")
		validation = validate_run(run_name)
		assert validation["counts"]["error"] == 0, [
			issue for issue in validation["issues"] if issue["severity"] == "error"
		]
		capabilities = json.loads(
			frappe.db.get_value("Scenario Run", run_name, "published_capabilities") or "{}"
		)
		assert all(capabilities.get(capability) for capability in archetype.required_capabilities)
	finally:
		cleanup = cleanup_run(run_name)
		assert cleanup["blockers"] == []
		assert cleanup["status"] == "Cleaned Up"


def test_a_generated_scenario_records_everything_it_created(generated):
	import frappe

	manifest = load_manifest(generated["run_id"])

	# The reported count is of created records. The manifest also carries the
	# settings a run changed, which cleanup restores rather than deletes.
	assert len(manifest.created()) == generated["record_count"]
	assert len(manifest) > len(manifest.created())
	assert generated["canonical_hash"]
	assert generated["structural_hash"]
	baseline = frappe.get_doc(
		"Scenario Checkpoint",
		frappe.db.get_value(
			"Scenario Checkpoint",
			{"scenario_run": generated["run_id"], "checkpoint_type": "Baseline"},
			"name",
		),
	)
	assert baseline.record_count == len(manifest.created())


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


def test_operational_breadth_uses_real_linked_erpnext_documents(generated):
	import json

	import frappe

	run = frappe.get_doc("Scenario Run", generated["run_id"])
	capabilities = json.loads(run.published_capabilities or "{}")

	crm = capabilities["erpnext.commercial.crm"]
	assert crm["opportunities"]
	assert crm["quotations"]
	for row in crm["quotations"]:
		quotation = frappe.db.get_value("Quotation", row["name"], ["docstatus", "opportunity"], as_dict=True)
		assert quotation.docstatus == 1
		assert quotation.opportunity == row["opportunity"]

	taxes = capabilities["erpnext.commercial.taxes"]
	assert taxes["rate"] == 5
	assert frappe.db.exists("Sales Taxes and Charges Template", taxes["sales_template"])
	assert frappe.db.exists("Purchase Taxes and Charges Template", taxes["purchase_template"])
	assert frappe.db.exists("Sales Taxes and Charges", {"parenttype": "Sales Invoice"})
	assert frappe.db.exists("Purchase Taxes and Charges", {"parenttype": "Purchase Order"})

	purchase_returns = capabilities["erpnext.buying.returns"]
	assert {entry["doctype"] for entry in purchase_returns} == {
		"Purchase Invoice",
		"Purchase Receipt",
	}
	assert all(entry["return_against"] for entry in purchase_returns)

	transfers = capabilities["erpnext.commercial.stock_transfers"]
	assert transfers
	assert all(frappe.db.get_value("Stock Entry", row["name"], "docstatus") == 1 for row in transfers)

	reconciled = capabilities["erpnext.accounts.bank_reconciliation"]
	assert all(
		frappe.db.get_value("Bank Transaction", row["name"], "status") == "Reconciled" for row in reconciled
	)

	closings = capabilities["erpnext.accounts.period_closing"]
	assert closings
	assert all(
		frappe.db.get_value("Period Closing Voucher", row["name"], "docstatus") == 1 for row in closings
	)


def test_completed_run_exposes_report_ready_outcomes(generated):
	assert generated["outcomes"]["master_data"]["customers"] > 0
	assert generated["outcomes"]["selling"]["invoice_count"] > 0
	assert generated["outcomes"]["selling"]["return_documents"] > 0
	assert generated["outcomes"]["buying"]["return_documents"] > 0
	assert generated["outcomes"]["commercial"]["quotations"] > 0
	assert "reconciled_bank_transactions" in generated["outcomes"]["accounting"]
	assert generated["outcomes"]["reports"]


def test_completed_run_has_a_chronological_story_linked_to_real_documents(generated):
	import frappe

	events = frappe.get_all(
		"Scenario Event",
		filters={"scenario_run": generated["run_id"]},
		fields=[
			"name",
			"sequence",
			"event_date",
			"reference_doctype",
			"reference_name",
			"previous_event",
			"next_event",
		],
		order_by="sequence asc",
	)
	assert len(events) == generated["event_count"] > 0
	assert [event.sequence for event in events] == list(range(1, len(events) + 1))
	assert [event.event_date for event in events] == sorted(event.event_date for event in events)
	assert events[0].previous_event is None
	assert events[-1].next_event is None
	assert all(frappe.db.exists(event.reference_doctype, event.reference_name) for event in events)

	explanation = explain_record(
		generated["run_id"],
		events[0].reference_doctype,
		events[0].reference_name,
	)
	assert explanation["event"]["why"]
	assert explanation["event"]["operational_effect"]
	assert explanation["event"]["ledger_effect"]
	assert explanation["event"]["stock_effect"]
	assert explanation["event"]["cancellation_consequence"]


def test_grounded_tutor_cites_real_scenario_evidence_and_remains_read_only(generated, rollback):
	import json

	import frappe

	from frappe_scenario.ai.executor import AIHTTPResult
	from frappe_scenario.ai.tutor import ask_tutor, confirm_corrections

	frappe.get_doc(
		{
			"doctype": "Scenario AI Provider",
			"provider": "openai",
			"enabled": 1,
			"credential": "tutor-test-secret",
		}
	).insert()
	ledger_before = frappe.db.count("GL Entry")
	stock_before = frappe.db.count("Stock Ledger Entry")

	def transport(endpoint, body, headers, timeout):
		request_input = json.loads(body["input"][0]["content"][0]["text"])
		evidence = request_input["evidence"]["items"]
		event = next(
			item for item in evidence if item["kind"] == "scenario" and item["doctype"] == "Scenario Event"
		)
		document = next(
			item
			for item in evidence
			if item["kind"] == "scenario" and item["doctype"] not in {"Scenario Run", "Scenario Event"}
		)
		metadata = next(item for item in evidence if item["kind"] == "erpnext_metadata")
		output = {
			"answer": "This scenario event is linked to a normal ERPNext document.",
			"claims": [
				{
					"kind": "scenario_fact",
					"text": "The generated event links to this document.",
					"evidence_ids": [event["id"], document["id"]],
				},
				{
					"kind": "erpnext_fact",
					"text": "The document behavior comes from its ERPNext metadata.",
					"evidence_ids": [metadata["id"]],
				},
			],
			"proposed_corrections": [
				{
					"target_evidence_id": document["id"],
					"description": "Review the document before considering any correction.",
					"requires_confirmation": True,
				}
			],
		}
		return AIHTTPResult(
			200,
			{
				"id": "resp_tutor_test",
				"output": [
					{
						"type": "message",
						"content": [{"type": "output_text", "text": json.dumps(output)}],
					}
				],
			},
		)

	result = ask_tutor(
		generated["run_id"],
		"Why does this document exist and what should I inspect?",
		transport=transport,
	)
	assert result["status"] == "Correction Proposed"
	assert result["read_only"] is True
	assert result["executed_actions"] == []
	assert all(citation["name"] for citation in result["citations"])
	confirmed = confirm_corrections(result["exchange"])
	assert confirmed["status"] == "Correction Confirmed"
	assert confirmed["executed_actions"] == []
	assert frappe.db.count("GL Entry") == ledger_before
	assert frappe.db.count("Stock Ledger Entry") == stock_before


@pytest.mark.parametrize("path_key", ["buying", "selling"])
def test_novice_can_complete_core_paths_against_real_erpnext_records(generated, path_key):
	import frappe

	home = learning_home(generated["run_id"])
	path = next(path for path in home["paths"] if path["key"] == path_key)
	missing_steps = set(path["availability"]["missing_steps"])
	result = None
	for lesson in path["lessons"]:
		for step in lesson["steps"]:
			if f"{lesson['key']}/{step['key']}" in missing_steps:
				continue
			result = verify_step(generated["run_id"], path_key, lesson["key"], step["key"])
			assert result["passed"], result

	assert result
	progress = frappe.get_doc("Scenario Learner Progress", result["progress"]["name"])
	assert progress.user == frappe.session.user
	assert result["progress"]["completed"] == result["progress"]["total"] - len(missing_steps)
	assert progress.status == ("Completed" if not missing_steps else "In Progress")


def test_learner_changes_are_visible_and_manifest_scoped_resets_restore_them(generated):
	import frappe

	manifest = load_manifest(generated["run_id"])
	lead = next(
		record for record in manifest.for_capability("erpnext.parties.leads") if record.operation == "created"
	)
	original = frappe.db.get_value(lead.doctype, lead.name, "first_name")
	frappe.db.set_value(lead.doctype, lead.name, "first_name", "Learner Experiment")

	changes = describe_changes(generated["run_id"])
	change = next(item for item in changes["changes"] if item["reference"] == lead.reference)
	assert change["status"] == "Changed"
	assert "first_name" in change["fields"]

	result = reset_module(generated["run_id"], "crm-parties")
	assert not result["blockers"]
	assert frappe.db.get_value(lead.doctype, lead.name, "first_name") == original

	learner_record = frappe.get_doc(
		{"doctype": "ToDo", "description": "Learner-owned note outside the scenario manifest"}
	).insert(ignore_permissions=True)
	try:
		assert not restore_scenario(generated["run_id"])["blockers"]
		assert frappe.db.exists("ToDo", learner_record.name)
	finally:
		frappe.delete_doc("ToDo", learner_record.name, ignore_permissions=True, delete_permanently=True)


def test_named_checkpoint_can_restore_a_later_owned_state(generated):
	import frappe

	manifest = load_manifest(generated["run_id"])
	lead = next(
		record for record in manifest.for_capability("erpnext.parties.leads") if record.operation == "created"
	)
	frappe.db.set_value(lead.doctype, lead.name, "first_name", "Checkpoint Name")
	checkpoint = create_checkpoint(generated["run_id"], "Before contact exercise")
	frappe.db.set_value(lead.doctype, lead.name, "first_name", "Changed Again")

	result = restore_scenario(generated["run_id"], checkpoint_name=checkpoint["name"])

	assert not result["blockers"]
	assert frappe.db.get_value(lead.doctype, lead.name, "first_name") == "Checkpoint Name"
	baseline = restore_scenario(generated["run_id"])
	assert not baseline["blockers"]


def test_troubleshooting_lab_injects_checks_and_restores_a_pricing_problem(generated):
	import frappe

	home = lab_home(generated["run_id"])
	pricing = next(problem for problem in home["problems"] if problem["key"] == "pricing-error")
	assert pricing["availability"]["available"]

	case = activate_problem(generated["run_id"], "pricing-error")
	target = case["target"]
	injected_rate = frappe.db.get_value(target["doctype"], target["name"], "price_list_rate")
	wrong = check_diagnosis(case["name"], "wrong-uom")
	assert not wrong["passed"]
	assert wrong["hints"]
	correct = check_diagnosis(case["name"], "price-below-cost")
	assert correct["passed"]

	restored = restore_case(case["name"])
	assert not restored["blockers"]
	assert frappe.db.get_value(target["doctype"], target["name"], "price_list_rate") > injected_rate
	assert lab_home(generated["run_id"])["active_case"] is None


def test_troubleshooting_lab_removes_its_unallocated_payment_draft(generated):
	import frappe

	home = lab_home(generated["run_id"])
	problem = next(problem for problem in home["problems"] if problem["key"] == "unreconciled-payment")
	if not problem["availability"]["available"]:
		pytest.skip(problem["availability"]["message"])
	case = activate_problem(generated["run_id"], "unreconciled-payment")
	assert case["target"]["doctype"] == "Payment Entry"
	assert frappe.db.exists("Payment Entry", case["target"]["name"])

	restored = restore_case(case["name"])
	assert not restored["blockers"]
	assert not frappe.db.exists("Payment Entry", case["target"]["name"])


@pytest.mark.parametrize(
	"problem_key",
	["overdue-account", "partial-delivery", "stock-shortage", "credit-limit-breach", "posting-period"],
)
def test_every_remaining_troubleshooting_injector_can_be_restored(generated, problem_key):
	home = lab_home(generated["run_id"])
	problem = next(problem for problem in home["problems"] if problem["key"] == problem_key)
	if not problem["availability"]["available"]:
		pytest.skip(problem["availability"]["message"])
	case = activate_problem(generated["run_id"], problem_key)

	result = restore_case(case["name"])

	assert not result["blockers"]
	assert result["case"]["status"] == "Restored"


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
	import frappe

	first_projection = canonical_projection(load_manifest(generated["run_id"]))
	active_lab = activate_problem(generated["run_id"], "stock-shortage")
	lab_target = active_lab["target"]
	first_cleanup = cleanup_run(generated["run_id"])
	assert first_cleanup["blockers"] == []
	assert not frappe.db.exists(lab_target["doctype"], lab_target["name"])
	assert not frappe.db.exists("Scenario Lab Case", active_lab["name"])

	second = _generate(smoke_specification)
	try:
		second_projection = canonical_projection(load_manifest(second["run_id"]))
		assert second_projection == first_projection, _first_difference(first_projection, second_projection)
		assert second["canonical_hash"] == generated["canonical_hash"]
		assert second["record_count"] == generated["record_count"]
	finally:
		assert cleanup_run(second["run_id"])["blockers"] == []


@pytest.mark.parametrize(
	"doctype",
	[
		"Company",
		"Customer",
		"Supplier",
		"Item",
		"GL Entry",
		"Scenario Event",
		"Scenario Lab Case",
	],
)
def test_cleanup_leaves_nothing_behind(generated, doctype):
	"""Runs after the determinism test, by which point both runs are cleaned."""
	import frappe

	assert frappe.db.count(doctype) == 0
