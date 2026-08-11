# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Resolve the closed scenario-binding vocabulary to real ERPNext targets."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import frappe
from frappe import _


def resolve_binding(run: Any, binding: str, *, fieldname: str | None = None) -> dict[str, Any]:
	parts = binding.split(":")
	kind = parts[0]
	if kind == "event" and len(parts) == 3 and parts[2] in {"first", "next"}:
		target = _event_target(run, parts[1], parts[2])
	elif kind == "related" and len(parts) == 2:
		target = _event_target(run, parts[1], "first")
	elif kind == "scenario" and len(parts) == 2:
		target = _scenario_target(run, parts[1])
	elif kind == "capability" and len(parts) == 3 and parts[2] in {"first", "next"}:
		target = _capability_target(run, parts[1], parts[2])
	elif kind == "report" and len(parts) == 2:
		target = _report_target(parts[1])
	elif kind == "doctype" and len(parts) == 2:
		target = _doctype_target(parts[1])
	else:
		raise frappe.ValidationError(_("Unsupported scenario binding: {0}").format(binding))

	if fieldname:
		doctype = target.get("doctype")
		if not doctype or not frappe.get_meta(doctype).has_field(fieldname):
			raise frappe.ValidationError(
				_("Field {0} is unavailable on the resolved tutorial target.").format(fieldname)
			)
		target["fieldname"] = fieldname
	target["binding"] = binding
	return target


def _event_target(run: Any, key: str, position: str) -> dict[str, Any]:
	events = frappe.get_all(
		"Scenario Event",
		filters={"scenario_run": run.name},
		fields=["event_type", "reference_doctype", "reference_name"],
		order_by="sequence asc",
	)
	matches = [event for event in events if _key(event.event_type) == key or _key(event.reference_doctype) == key]
	index = 1 if position == "next" and len(matches) > 1 else 0
	if not matches:
		raise frappe.DoesNotExistError(_("The scenario has no event bound as {0}.").format(key))
	event = matches[index]
	return _document_target(event.reference_doctype, event.reference_name)


def _scenario_target(run: Any, key: str) -> dict[str, Any]:
	if key == "run":
		return _document_target("Scenario Run", run.name)
	if key == "company":
		return _document_target("Company", run.company)
	if key == "default_warehouse":
		capabilities = json.loads(run.published_capabilities or "{}")
		warehouse = (capabilities.get("erpnext.catalog.warehouses") or {}).get("default")
		return _document_target("Warehouse", warehouse)
	if key == "fiscal_year":
		name = frappe.db.get_value(
			"Fiscal Year",
			{
				"year_start_date": ["<=", run.anchor_date],
				"year_end_date": [">=", run.anchor_date],
				"disabled": 0,
			},
			"name",
		)
		return _document_target("Fiscal Year", name)
	raise frappe.ValidationError(_("Unsupported scenario target: {0}").format(key))


def _capability_target(run: Any, capability: str, position: str) -> dict[str, Any]:
	capabilities = json.loads(run.published_capabilities or "{}")
	entries = capabilities.get(capability) or []
	if isinstance(entries, dict):
		entries = entries.get("all") or list(entries.values())
	if not isinstance(entries, list):
		entries = [entries]
	index = 1 if position == "next" and len(entries) > 1 else 0
	if not entries:
		raise frappe.DoesNotExistError(_("The scenario capability {0} is empty.").format(capability))
	entry = entries[index]
	name = entry.get("name") if isinstance(entry, dict) else str(entry)
	doctype = {
		"erpnext.parties.leads": "Lead",
		"erpnext.parties.customers": "Customer",
		"erpnext.parties.suppliers": "Supplier",
		"erpnext.catalog.items": "Item",
	}.get(capability)
	if not doctype:
		raise frappe.ValidationError(_("Capability {0} has no document binding.").format(capability))
	return _document_target(doctype, name)


def _report_target(key: str) -> dict[str, Any]:
	name = next(
		(report for report in frappe.get_all("Report", pluck="name") if _key(report) == key),
		None,
	)
	if not name:
		raise frappe.DoesNotExistError(_("The bound ERPNext report is unavailable."))
	return {"report": name, "route": f"/app/query-report/{quote(name)}", "fieldname": None}


def _doctype_target(key: str) -> dict[str, Any]:
	name = next(
		(doctype for doctype in frappe.get_all("DocType", pluck="name") if _key(doctype) == key),
		None,
	)
	if not name:
		raise frappe.DoesNotExistError(_("The bound ERPNext DocType is unavailable."))
	return {"doctype": name, "name": None, "route": f"/app/{frappe.scrub(name).replace('_', '-')}", "fieldname": None}


def _document_target(doctype: str, name: str | None) -> dict[str, Any]:
	if not name or not frappe.db.exists(doctype, name):
		raise frappe.DoesNotExistError(_("The scenario-bound document no longer exists."))
	return {
		"doctype": doctype,
		"name": name,
		"route": f"/app/{frappe.scrub(doctype).replace('_', '-')}/{quote(str(name))}",
		"fieldname": None,
	}


def _key(value: str) -> str:
	return "_".join(str(value).strip().lower().replace("/", " ").replace("-", " ").split())
