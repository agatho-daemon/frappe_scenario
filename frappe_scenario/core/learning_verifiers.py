# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Closed, server-authoritative verification vocabulary for learning steps."""

from __future__ import annotations

import datetime
import json
from collections.abc import Callable
from typing import Any

import frappe
from frappe import _

from frappe_scenario.core.engine import load_manifest
from frappe_scenario.core.learning_bindings import resolve_binding

Verifier = Callable[[Any, dict[str, Any], dict[str, Any]], dict[str, Any]]


def verify_named(
	run: Any,
	*,
	verifier: str,
	binding: str,
	configuration: dict[str, Any] | None = None,
) -> dict[str, Any]:
	"""Resolve a trusted semantic binding and invoke one registered verifier."""
	if verifier not in VERIFIERS:
		raise frappe.ValidationError(f"Unsupported learning verifier: {verifier}")
	target = resolve_binding(run, binding)
	return VERIFIERS[verifier](run, target, dict(configuration or {}))


def _document_exists(run: Any, target: dict[str, Any], configuration: dict[str, Any]) -> dict[str, Any]:
	doctype, name = target.get("doctype"), target.get("name")
	if name is None:
		passed = bool(doctype and frappe.db.exists("DocType", doctype))
	else:
		passed = bool(doctype and frappe.db.exists(doctype, name))
	return _result(passed, _("Verified the scenario-bound document."), target=target)


def _document_submitted(run: Any, target: dict[str, Any], configuration: dict[str, Any]) -> dict[str, Any]:
	passed = bool(
		target.get("doctype")
		and target.get("name")
		and int(frappe.db.get_value(target["doctype"], target["name"], "docstatus") or 0) == 1
	)
	return _result(passed, _("Verified the submitted ERPNext document."), target=target)


def _field_equals(run: Any, target: dict[str, Any], configuration: dict[str, Any]) -> dict[str, Any]:
	fieldname = _field(target, configuration)
	actual = frappe.db.get_value(target["doctype"], target["name"], fieldname)
	expected = configuration.get("expected")
	return _result(
		actual == expected, _("Verified the expected field value."), actual=actual, expected=expected
	)


def _child_table_has_rows(run: Any, target: dict[str, Any], configuration: dict[str, Any]) -> dict[str, Any]:
	fieldname = _field(target, configuration, table_only=True)
	field = frappe.get_meta(target["doctype"]).get_field(fieldname)
	count = frappe.db.count(field.options, {"parenttype": target["doctype"], "parent": target["name"]})
	minimum = max(1, int(configuration.get("minimum") or 1))
	return _result(count >= minimum, _("Verified the document's child rows."), count=count, minimum=minimum)


def _link_references(run: Any, target: dict[str, Any], configuration: dict[str, Any]) -> dict[str, Any]:
	fieldname = _field(target, configuration)
	field = frappe.get_meta(target["doctype"]).get_field(fieldname)
	if field.fieldtype not in {"Link", "Dynamic Link"}:
		raise frappe.ValidationError(_("The configured field is not a Link field."))
	value = frappe.db.get_value(target["doctype"], target["name"], fieldname)
	link_doctype = field.options
	if field.fieldtype == "Dynamic Link":
		link_doctype = frappe.db.get_value(target["doctype"], target["name"], field.options)
	passed = bool(value and link_doctype and frappe.db.exists(link_doctype, value))
	return _result(passed, _("Verified the linked ERPNext record."), doctype=link_doctype, name=value)


def _invoice_outstanding_reduced(
	run: Any, target: dict[str, Any], configuration: dict[str, Any]
) -> dict[str, Any]:
	if target.get("doctype") not in {"Sales Invoice", "Purchase Invoice"}:
		raise frappe.ValidationError(_("Outstanding verification requires an invoice binding."))
	values = frappe.db.get_value(
		target["doctype"], target["name"], ["grand_total", "outstanding_amount"], as_dict=True
	)
	grand_total = abs(float(values.grand_total or 0))
	outstanding = abs(float(values.outstanding_amount or 0))
	return _result(
		outstanding < grand_total,
		_("Verified that payment reduced the invoice balance."),
		grand_total=grand_total,
		outstanding=outstanding,
	)


def _stock_quantity_changed(
	run: Any, target: dict[str, Any], configuration: dict[str, Any]
) -> dict[str, Any]:
	rows = frappe.get_all(
		"Stock Ledger Entry",
		filters={"voucher_type": target["doctype"], "voucher_no": target["name"], "is_cancelled": 0},
		pluck="actual_qty",
	)
	quantity = sum(float(value or 0) for value in rows)
	return _result(
		abs(float(quantity)) > 0, _("Verified the voucher's stock quantity change."), quantity=quantity
	)


def _ledger_voucher_balanced(
	run: Any, target: dict[str, Any], configuration: dict[str, Any]
) -> dict[str, Any]:
	rows = frappe.get_all(
		"GL Entry",
		filters={"voucher_type": target["doctype"], "voucher_no": target["name"], "is_cancelled": 0},
		fields=["debit", "credit"],
	)
	difference = sum(float(row.debit or 0) - float(row.credit or 0) for row in rows)
	tolerance = abs(float(configuration.get("tolerance") or 0.005))
	return _result(
		bool(rows) and abs(difference) <= tolerance,
		_("Verified the voucher's balanced ledger entries."),
		entries=len(rows),
		difference=difference,
	)


def _report_contains_record(
	run: Any, target: dict[str, Any], configuration: dict[str, Any]
) -> dict[str, Any]:
	report = target.get("report")
	record_binding = configuration.get("record_binding")
	if not report or not frappe.db.exists("Report", report) or not record_binding:
		return _result(False, _("The report or record binding is unavailable."))
	record = resolve_binding(run, record_binding)
	adapter = REPORT_RECORD_ADAPTERS.get(report)
	if not adapter:
		raise frappe.ValidationError(_("The report has no registered learning verifier adapter."))
	passed = adapter(record)
	return _result(
		passed,
		_("Verified the scenario record in the registered report data."),
		report=report,
		record=record,
	)


def _general_ledger_contains(record: dict[str, Any]) -> bool:
	return bool(
		record.get("doctype")
		and record.get("name")
		and frappe.db.exists(
			"GL Entry",
			{
				"voucher_type": record["doctype"],
				"voucher_no": record["name"],
				"is_cancelled": 0,
			},
		)
	)


REPORT_RECORD_ADAPTERS: dict[str, Callable[[dict[str, Any]], bool]] = {
	"General Ledger": _general_ledger_contains,
}


def _report_available(run: Any, target: dict[str, Any], configuration: dict[str, Any]) -> dict[str, Any]:
	return _result(
		bool(target.get("report") and frappe.db.exists("Report", target["report"])),
		_("Verified the ERPNext report."),
		target=target,
	)


def _doctype_exists(run: Any, target: dict[str, Any], configuration: dict[str, Any]) -> dict[str, Any]:
	return _result(
		bool(target.get("doctype") and frappe.db.exists("DocType", target["doctype"])),
		_("Verified the ERPNext DocType."),
		target=target,
	)


def _company_accounts(run: Any, target: dict[str, Any], configuration: dict[str, Any]) -> dict[str, Any]:
	count = frappe.db.count("Account", {"company": run.company, "disabled": 0})
	return _result(bool(count), _("Verified active company accounts."), count=count)


def _party_links(run: Any, target: dict[str, Any], configuration: dict[str, Any]) -> dict[str, Any]:
	counts = {doctype: 0 for doctype in ("Address", "Contact")}
	for record in load_manifest(run).created():
		if record.doctype in counts:
			counts[record.doctype] += 1
	return _result(all(counts.values()), _("Verified scenario-owned contacts and addresses."), counts=counts)


def _validation_passed(run: Any, target: dict[str, Any], configuration: dict[str, Any]) -> dict[str, Any]:
	summary = json.loads(run.validation_summary or "{}")
	return _result(
		bool(summary.get("passed")),
		_("Verified successful scenario validation."),
		counts=summary.get("counts"),
	)


def _return_source(run: Any, target: dict[str, Any], configuration: dict[str, Any]) -> dict[str, Any]:
	doc = frappe.get_doc(target["doctype"], target["name"])
	source = doc.get("return_against")
	return _result(
		bool(source and frappe.db.exists(target["doctype"], source)),
		_("Verified the return's source document."),
		source=source,
	)


def _fiscal_year(run: Any, target: dict[str, Any], configuration: dict[str, Any]) -> dict[str, Any]:
	anchor = datetime.date.fromisoformat(str(run.anchor_date))
	passed = bool(
		target.get("name")
		and frappe.db.exists(
			"Fiscal Year",
			{
				"name": target["name"],
				"year_start_date": ["<=", anchor],
				"year_end_date": [">=", anchor],
				"disabled": 0,
			},
		)
	)
	return _result(passed, _("Verified the fiscal year covering the scenario."), target=target)


def _field(target: dict[str, Any], configuration: dict[str, Any], *, table_only: bool = False) -> str:
	fieldname = str(configuration.get("fieldname") or "")
	if not target.get("doctype") or not target.get("name") or not fieldname:
		raise frappe.ValidationError(_("A document binding and fieldname are required."))
	field = frappe.get_meta(target["doctype"]).get_field(fieldname)
	if not field or (table_only and field.fieldtype != "Table"):
		raise frappe.ValidationError(_("The configured field is unavailable for this verifier."))
	return fieldname


def _result(passed: bool, message: str, **evidence: Any) -> dict[str, Any]:
	if not passed:
		message = _("The ERPNext state required by this lesson step was not verified.")
	return {"passed": bool(passed), "message": message, "evidence": evidence}


VERIFIERS: dict[str, Verifier] = {
	"document.exists": _document_exists,
	"document.submitted": _document_submitted,
	"field.equals": _field_equals,
	"child_table.has_rows": _child_table_has_rows,
	"link.references": _link_references,
	"invoice.outstanding_reduced": _invoice_outstanding_reduced,
	"stock.quantity_changed": _stock_quantity_changed,
	"ledger.voucher_balanced": _ledger_voucher_balanced,
	"report.contains_record": _report_contains_record,
	"report.available": _report_available,
	"doctype.exists": _doctype_exists,
	"scenario.company_accounts_exist": _company_accounts,
	"scenario.party_links_exist": _party_links,
	"scenario.validation_passed": _validation_passed,
	"document.return_source_exists": _return_source,
	"scenario.fiscal_year_covers_run": _fiscal_year,
}
