# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Deterministic, reversible ERPNext troubleshooting exercises."""

from __future__ import annotations

import datetime
import json
from collections.abc import Callable
from typing import Any

import frappe
from frappe import _
from frappe.utils import add_days, flt, now_datetime

from frappe_scenario.core.engine import load_manifest
from frappe_scenario.core.experimentation import create_checkpoint, restore_scenario
from frappe_scenario.core.troubleshooting_catalog import CATALOG_VERSION, PROBLEMS, get_problem

CASE_DOCTYPE = "Scenario Lab Case"


def lab_home(run_name: str) -> dict[str, Any]:
	run = _completed_run(run_name)
	active = _active_case(run.name)
	return {
		"run": {"name": run.name, "title": run.title, "company": run.company},
		"catalog_version": CATALOG_VERSION,
		"active_case": _case_payload(active) if active else None,
		"problems": [
			{
				**_public_problem(problem),
				"availability": _availability(run, problem),
			}
			for problem in PROBLEMS
		],
		"history": [
			_case_payload(frappe.get_doc(CASE_DOCTYPE, name))
			for name in frappe.get_all(
				CASE_DOCTYPE,
				filters={"scenario_run": run.name, "status": "Restored"},
				pluck="name",
				order_by="activated_at desc",
				limit=20,
			)
		],
	}


def activate_problem(run_name: str, problem_key: str, *, user: str | None = None) -> dict[str, Any]:
	run = _completed_run(run_name)
	if _active_case(run.name):
		frappe.throw(_("Restore the active lab case before starting another one."), frappe.ValidationError)
	try:
		problem = get_problem(problem_key)
	except KeyError:
		frappe.throw(_("Unknown troubleshooting problem."), frappe.DoesNotExistError)
	availability = _availability(run, problem)
	if not availability["available"]:
		frappe.throw(availability["message"], frappe.ValidationError)

	checkpoint = create_checkpoint(run.name, f"Before lab: {problem['title']}", user=user)
	injected = INJECTORS[problem["injector"]](run)
	doc = frappe.get_doc(
		{
			"doctype": CASE_DOCTYPE,
			"scenario_run": run.name,
			"problem_key": problem["key"],
			"catalog_version": CATALOG_VERSION,
			"title": problem["title"],
			"module_name": problem["module"],
			"difficulty": problem["difficulty"],
			"status": "Active",
			"objective": problem["objective"],
			"diagnosis_choices": json.dumps(problem["choices"], indent="\t"),
			"hints": json.dumps(problem["hints"], indent="\t"),
			"checkpoint": checkpoint["name"],
			"target_doctype": injected["target_doctype"],
			"target_name": injected["target_name"],
			"evidence": json.dumps(injected.get("evidence") or {}, indent="\t", default=str),
			"injected_changes": json.dumps(injected.get("changes") or [], indent="\t", default=str),
			"created_records": json.dumps(injected.get("created") or [], indent="\t", default=str),
			"activated_by": user or frappe.session.user,
			"activated_at": now_datetime(),
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()
	return _case_payload(doc)


def check_diagnosis(case_name: str, diagnosis_key: str) -> dict[str, Any]:
	doc = frappe.get_doc(CASE_DOCTYPE, case_name)
	doc.check_permission("read")
	if doc.status not in {"Active", "Diagnosed"}:
		frappe.throw(_("This lab case is no longer active."), frappe.ValidationError)
	problem = get_problem(doc.problem_key)
	valid = {choice["key"] for choice in problem["choices"]}
	if diagnosis_key not in valid:
		frappe.throw(_("Choose one of the supplied diagnoses."), frappe.ValidationError)
	passed = diagnosis_key == problem["accepted_diagnosis"]
	doc.attempts = int(doc.attempts or 0) + 1
	doc.last_diagnosis = diagnosis_key
	if passed:
		doc.status = "Diagnosed"
		doc.diagnosed_at = now_datetime()
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {
		"passed": passed,
		"message": _("Correct. Restore the case when you are ready.")
		if passed
		else _("That does not explain the evidence yet. Review the hint and try again."),
		"hints": problem["hints"][: min(doc.attempts, len(problem["hints"]))],
		"case": _case_payload(doc),
	}


def restore_case(case_name: str) -> dict[str, Any]:
	doc = frappe.get_doc(CASE_DOCTYPE, case_name)
	doc.check_permission("read")
	if doc.status == "Restored":
		return {"case": _case_payload(doc), "blockers": [], "restored": 0}

	blockers: list[dict[str, Any]] = []
	for record in reversed(json.loads(doc.created_records or "[]")):
		if not frappe.db.exists(record["doctype"], record["name"]):
			continue
		created = frappe.get_doc(record["doctype"], record["name"])
		if int(created.docstatus) != 0:
			blockers.append(
				{
					"reference": f"{created.doctype}/{created.name}",
					"message": _(
						"A lab-created draft was submitted or cancelled. Return it to Draft before restoring the lab."
					),
				}
			)
	if blockers:
		return {"case": _case_payload(doc), "blockers": blockers, "restored": 0}

	# Restore manifest-owned records first. Its reset is atomic, so a blocker
	# leaves the lab-created drafts intact and available for inspection.
	result = restore_scenario(doc.scenario_run, checkpoint_name=doc.checkpoint, reset_progress=False)
	if result["blockers"]:
		return {"case": _case_payload(doc), "blockers": result["blockers"], "restored": 0}

	created_references = {
		(record["doctype"], record["name"]) for record in json.loads(doc.created_records or "[]")
	}
	if (doc.target_doctype, doc.target_name) in created_references:
		doc.target_name = None
		doc.save(ignore_permissions=True)
	for record in reversed(json.loads(doc.created_records or "[]")):
		if frappe.db.exists(record["doctype"], record["name"]):
			frappe.delete_doc(
				record["doctype"], record["name"], ignore_permissions=True, delete_permanently=True
			)
	doc.status = "Restored"
	doc.restored_at = now_datetime()
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"case": _case_payload(doc), "blockers": [], "restored": result["restored"]}


def discard_lab_cases(run_name: str) -> list[dict[str, Any]]:
	"""Restore active cases before scenario cleanup and remove lab metadata."""
	blockers: list[dict[str, Any]] = []
	for name in frappe.get_all(CASE_DOCTYPE, filters={"scenario_run": run_name}, pluck="name"):
		doc = frappe.get_doc(CASE_DOCTYPE, name)
		if doc.status != "Restored":
			result = restore_case(name)
			blockers.extend(result["blockers"])
	if blockers:
		return blockers
	frappe.db.delete(CASE_DOCTYPE, {"scenario_run": run_name})
	frappe.db.commit()
	return []


def _availability(run: Any, problem: dict[str, Any]) -> dict[str, Any]:
	available, reason = AVAILABILITY[problem["injector"]](run)
	return {"available": available, "message": reason}


def _has_doctype(run: Any, doctype: str) -> tuple[bool, str | None]:
	manifest = load_manifest(run)
	available = any(
		record.doctype == doctype and frappe.db.exists(doctype, record.name) for record in manifest.created()
	)
	return available, None if available else _("This dataset has no scenario-owned {0} record.").format(
		doctype
	)


def _has_overdue(run: Any) -> tuple[bool, str | None]:
	name = _overdue_invoice(run)
	return bool(name), None if name else _("This dataset has no overdue submitted Sales Invoice.")


def _has_partial(run: Any) -> tuple[bool, str | None]:
	event = _partial_delivery_event(run)
	return bool(event), None if event else _("This dataset has no partial Delivery Note story.")


def _public_problem(problem: dict[str, Any]) -> dict[str, Any]:
	return {key: value for key, value in problem.items() if key not in {"injector", "accepted_diagnosis"}}


def _active_case(run_name: str) -> Any | None:
	name = frappe.db.get_value(
		CASE_DOCTYPE, {"scenario_run": run_name, "status": ["in", ["Active", "Diagnosed"]]}, "name"
	)
	return frappe.get_doc(CASE_DOCTYPE, name) if name else None


def _case_payload(doc: Any) -> dict[str, Any]:
	return {
		"name": doc.name,
		"run": doc.scenario_run,
		"problem_key": doc.problem_key,
		"title": doc.title,
		"module": doc.module_name,
		"difficulty": doc.difficulty,
		"status": doc.status,
		"objective": doc.objective,
		"choices": json.loads(doc.diagnosis_choices or "[]"),
		"hints": json.loads(doc.hints or "[]")[
			: min(int(doc.attempts or 0), len(json.loads(doc.hints or "[]")))
		],
		"attempts": int(doc.attempts or 0),
		"target": {
			"doctype": doc.target_doctype,
			"name": doc.target_name,
			"route": f"/app/{frappe.scrub(doc.target_doctype).replace('_', '-')}/{doc.target_name}",
		},
		"evidence": json.loads(doc.evidence or "{}"),
		"checkpoint": doc.checkpoint,
	}


def _completed_run(run_name: str) -> Any:
	run = frappe.get_doc("Scenario Run", run_name)
	run.check_permission("read")
	if run.status != "Completed":
		frappe.throw(_("Troubleshooting requires a completed Scenario Run."), frappe.ValidationError)
	return run


def _owned_name(run: Any, doctype: str, *, filters: dict[str, Any] | None = None) -> str | None:
	manifest = load_manifest(run)
	for record in manifest.created():
		if record.doctype != doctype or not frappe.db.exists(doctype, record.name):
			continue
		if not filters or all(
			frappe.db.get_value(doctype, record.name, field) == value for field, value in filters.items()
		):
			return record.name
	return None


def _overdue_invoice(run: Any) -> str | None:
	manifest = load_manifest(run)
	for record in manifest.created():
		if record.doctype != "Sales Invoice" or not frappe.db.exists(record.doctype, record.name):
			continue
		docstatus, due_date, outstanding = frappe.db.get_value(
			record.doctype, record.name, ["docstatus", "due_date", "outstanding_amount"]
		)
		if int(docstatus or 0) == 1 and due_date and due_date < run.anchor_date and flt(outstanding) > 0:
			return record.name
	return None


def _partial_delivery_event(run: Any) -> Any | None:
	for event in frappe.get_all(
		"Scenario Event",
		filters={"scenario_run": run.name, "event_type": "Delivery Note"},
		fields=["reference_doctype", "reference_name", "related_documents"],
		order_by="sequence asc",
	):
		doc = frappe.get_doc(event.reference_doctype, event.reference_name)
		if any(
			flt(row.qty)
			< flt(
				(row.so_detail and frappe.db.get_value("Sales Order Item", row.so_detail, "qty")) or row.qty
			)
			for row in doc.items
		):
			return event
	return None


def _observe_overdue(run: Any) -> dict[str, Any]:
	name = _overdue_invoice(run)
	due_date, outstanding = frappe.db.get_value("Sales Invoice", name, ["due_date", "outstanding_amount"])
	return _injection(
		"Sales Invoice", name, evidence={"due_date": due_date, "outstanding_amount": outstanding}
	)


def _observe_partial_delivery(run: Any) -> dict[str, Any]:
	event = _partial_delivery_event(run)
	return _injection(
		event.reference_doctype,
		event.reference_name,
		evidence={"related_documents": json.loads(event.related_documents or "[]")},
	)


def _observe_posting_period(run: Any) -> dict[str, Any]:
	name = _owned_name(run, "Journal Entry")
	proposed = add_days(run.anchor_date, 400)
	return _injection("Journal Entry", name, evidence={"proposed_posting_date": proposed})


def _low_item_price(run: Any) -> dict[str, Any]:
	name = _owned_name(run, "Item Price", filters={"selling": 1}) or _owned_name(run, "Item Price")
	doc = frappe.get_doc("Item Price", name)
	original = doc.price_list_rate
	doc.price_list_rate = max(0.001, flt(original) * 0.05)
	doc.save(ignore_permissions=True)
	return _injection(
		"Item Price",
		name,
		changes=[{"doctype": "Item Price", "name": name, "field": "price_list_rate", "original": original}],
	)


def _low_credit_limit(run: Any) -> dict[str, Any]:
	invoice = _overdue_invoice(run) or _owned_name(run, "Sales Invoice")
	customer = frappe.db.get_value("Sales Invoice", invoice, "customer")
	doc = frappe.get_doc("Customer", customer)
	original = [row.as_dict(convert_dates_to_str=True) for row in doc.credit_limits]
	outstanding = sum(
		flt(value)
		for value in frappe.get_all(
			"Sales Invoice",
			filters={"customer": customer, "docstatus": 1},
			pluck="outstanding_amount",
		)
	)
	row = next((row for row in doc.credit_limits if row.company == run.company), None)
	if row:
		# This lab intentionally creates a state that the Customer controller
		# correctly refuses during normal editing. Write only the owned child row
		# after the checkpoint so the exercise is possible and fully restorable.
		frappe.db.set_value(
			row.doctype,
			row.name,
			{"credit_limit": outstanding, "bypass_credit_limit_check": 0},
			update_modified=False,
		)
	else:
		row = doc.append(
			"credit_limits",
			{"company": run.company, "credit_limit": outstanding, "bypass_credit_limit_check": 0},
		)
		row.db_insert()
	frappe.clear_document_cache("Customer", customer)
	source_name = _owned_name(run, "Sales Order", filters={"customer": customer})
	order = _draft_sales_order(run, source_name, quantity_multiplier=1)
	return _injection(
		"Sales Order",
		order.name,
		changes=[{"doctype": "Customer", "name": customer, "field": "credit_limits", "original": original}],
		created=[{"doctype": "Sales Order", "name": order.name}],
		evidence={
			"customer": customer,
			"current_outstanding": outstanding,
			"credit_limit": outstanding,
			"proposed_order_total": order.grand_total,
		},
	)


def _excess_sales_order(run: Any) -> dict[str, Any]:
	source_name = _owned_name(run, "Sales Order")
	doc = _draft_sales_order(run, source_name, quantity_multiplier=100)
	return _injection(
		"Sales Order",
		doc.name,
		created=[{"doctype": "Sales Order", "name": doc.name}],
		evidence={"source_sales_order": source_name},
	)


def _draft_sales_order(run: Any, source_name: str, *, quantity_multiplier: float) -> Any:
	source = frappe.get_doc("Sales Order", source_name)
	doc = frappe.copy_doc(source)
	doc.docstatus = 0
	doc.status = "Draft"
	doc.transaction_date = run.anchor_date
	doc.delivery_date = add_days(run.anchor_date, 7)
	doc.payment_schedule = []
	for row in doc.items:
		row.qty = max(flt(row.qty) * quantity_multiplier, 1000 if quantity_multiplier > 1 else 1)
		row.delivery_date = doc.delivery_date
		row.delivered_qty = 0
		row.billed_amt = 0
	doc.insert(ignore_permissions=True)
	return doc


def _unallocated_payment(run: Any) -> dict[str, Any]:
	invoice = _overdue_invoice(run) or _owned_name(run, "Sales Invoice")
	get_payment_entry = frappe.get_attr(
		"erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry"
	)
	doc = get_payment_entry("Sales Invoice", invoice)
	doc.references = []
	doc.posting_date = run.anchor_date
	doc.reference_no = f"LAB-{invoice}"
	doc.reference_date = run.anchor_date
	doc.insert(ignore_permissions=True)
	return _injection(
		"Payment Entry",
		doc.name,
		created=[{"doctype": "Payment Entry", "name": doc.name}],
		evidence={"invoice": invoice},
	)


def _injection(
	target_doctype: str,
	target_name: str,
	*,
	evidence: dict[str, Any] | None = None,
	changes: list[dict[str, Any]] | None = None,
	created: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
	return {
		"target_doctype": target_doctype,
		"target_name": target_name,
		"evidence": evidence or {},
		"changes": changes or [],
		"created": created or [],
	}


INJECTORS: dict[str, Callable[[Any], dict[str, Any]]] = {
	"unallocated_payment": _unallocated_payment,
	"observe_overdue": _observe_overdue,
	"observe_partial_delivery": _observe_partial_delivery,
	"excess_sales_order": _excess_sales_order,
	"low_item_price": _low_item_price,
	"low_credit_limit": _low_credit_limit,
	"observe_posting_period": _observe_posting_period,
}

AVAILABILITY: dict[str, Callable[[Any], tuple[bool, str | None]]] = {
	"unallocated_payment": _has_overdue,
	"observe_overdue": _has_overdue,
	"observe_partial_delivery": _has_partial,
	"excess_sales_order": lambda run: _has_doctype(run, "Sales Order"),
	"low_item_price": lambda run: _has_doctype(run, "Item Price"),
	"low_credit_limit": lambda run: _has_doctype(run, "Customer"),
	"observe_posting_period": lambda run: _has_doctype(run, "Journal Entry"),
}
