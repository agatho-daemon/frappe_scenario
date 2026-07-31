# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Scenario-bound learning catalogue, progress, and server verification."""

from __future__ import annotations

import datetime
import json
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import now_datetime

from frappe_scenario.core.engine import load_manifest
from frappe_scenario.core.learning_catalog import (
	CATALOG_VERSION,
	GLOSSARY,
	PATHS,
	flatten_steps,
	get_path,
	get_step,
)

PATH_DOCTYPE = "Scenario Learning Path"
PROGRESS_DOCTYPE = "Scenario Learner Progress"


def sync_learning_paths() -> None:
	"""Idempotently publish the versioned built-in catalogue as readable records."""
	if not frappe.db.table_exists(PATH_DOCTYPE):
		return
	for sequence, path in enumerate(PATHS, start=1):
		name = frappe.db.get_value(PATH_DOCTYPE, {"path_key": path["key"]}, "name")
		values = {
			"path_key": path["key"],
			"title": path["title"],
			"module_name": path["module"],
			"sequence": sequence,
			"description": path["description"],
			"path_version": CATALOG_VERSION,
			"lesson_definition": json.dumps(path["lessons"], indent="\t"),
			"enabled": 1,
		}
		if name:
			doc = frappe.get_doc(PATH_DOCTYPE, name)
			doc.update(values)
			doc.save(ignore_permissions=True)
		else:
			frappe.get_doc({"doctype": PATH_DOCTYPE, **values}).insert(ignore_permissions=True)


def learning_home(run_name: str, *, user: str | None = None) -> dict[str, Any]:
	run = _run(run_name)
	user = user or frappe.session.user
	capabilities = json.loads(run.published_capabilities or "{}")
	paths = []
	for path in PATHS:
		progress = _progress(run.name, path["key"], user, create=False)
		completed = _completed(progress)
		total = len(flatten_steps(path))
		paths.append(
			{
				**path,
				"version": CATALOG_VERSION,
				"availability": _availability(path, run, capabilities),
				"progress": {
					"status": progress.status if progress else "Not Started",
					"completed_steps": completed,
					"completed": len(completed),
					"total": total,
					"percent": round(len(completed) / total * 100) if total else 100,
					"current_step": progress.current_step if progress else None,
				},
			}
		)
	return {
		"run": {"name": run.name, "title": run.title, "company": run.company, "status": run.status},
		"paths": paths,
		"glossary": GLOSSARY,
	}


def verify_step(
	run_name: str,
	path_key: str,
	lesson_key: str,
	step_key: str,
	*,
	user: str | None = None,
) -> dict[str, Any]:
	"""Verify one ordered lesson step and persist per-user progress."""
	run = _run(run_name)
	user = user or frappe.session.user
	try:
		path = get_path(path_key)
		step = get_step(path_key, lesson_key, step_key)
	except KeyError:
		frappe.throw(_("Unknown learning path or lesson step."), frappe.DoesNotExistError)

	progress = _progress(run.name, path_key, user, create=True)
	completed = _completed(progress)
	step_id = f"{lesson_key}/{step_key}"
	ordered = [f"{lesson}/{candidate['key']}" for lesson, candidate in flatten_steps(path)]
	position = ordered.index(step_id)
	missing = [candidate for candidate in ordered[:position] if candidate not in completed]
	if missing:
		return {
			"passed": False,
			"message": _("Complete the preceding lesson step first."),
			"missing": missing,
			"progress": _progress_payload(progress, path),
		}

	verifier = VERIFIERS[step["verifier"]]
	evidence = verifier(run, step["configuration"])
	if not evidence["passed"]:
		return {**evidence, "progress": _progress_payload(progress, path)}

	if step_id not in completed:
		completed.append(step_id)
	progress.completed_steps = json.dumps(completed)
	progress.current_step = ordered[position + 1] if position + 1 < len(ordered) else None
	progress.status = "Completed" if len(completed) == len(ordered) else "In Progress"
	progress.started_at = progress.started_at or now_datetime()
	progress.completed_at = now_datetime() if progress.status == "Completed" else None
	progress.save(ignore_permissions=True)
	return {**evidence, "progress": _progress_payload(progress, path)}


def restart_path(run_name: str, path_key: str, *, user: str | None = None) -> dict[str, Any]:
	"""Reset progress only; data restoration is an explicit experimentation action."""
	run = _run(run_name)
	user = user or frappe.session.user
	path = get_path(path_key)
	progress = _progress(run.name, path_key, user, create=True)
	progress.completed_steps = "[]"
	progress.current_step = None
	progress.status = "Not Started"
	progress.started_at = None
	progress.completed_at = None
	progress.save(ignore_permissions=True)
	return _progress_payload(progress, path)


def _run(run_name: str) -> Any:
	run = frappe.get_doc("Scenario Run", run_name)
	run.check_permission("read")
	if run.status != "Completed":
		frappe.throw(_("Learning requires a completed Scenario Run."), frappe.ValidationError)
	return run


def _progress(run_name: str, path_key: str, user: str, *, create: bool) -> Any | None:
	name = frappe.db.get_value(
		PROGRESS_DOCTYPE,
		{"scenario_run": run_name, "path_key": path_key, "user": user},
		"name",
	)
	if name:
		return frappe.get_doc(PROGRESS_DOCTYPE, name)
	if not create:
		return None
	return frappe.get_doc(
		{
			"doctype": PROGRESS_DOCTYPE,
			"scenario_run": run_name,
			"path_key": path_key,
			"user": user,
			"path_version": CATALOG_VERSION,
			"status": "Not Started",
			"completed_steps": "[]",
		}
	).insert(ignore_permissions=True)


def _completed(progress: Any | None) -> list[str]:
	return json.loads(progress.completed_steps or "[]") if progress else []


def _progress_payload(progress: Any, path: dict[str, Any]) -> dict[str, Any]:
	completed = _completed(progress)
	total = len(flatten_steps(path))
	return {
		"name": progress.name,
		"status": progress.status,
		"completed_steps": completed,
		"current_step": progress.current_step,
		"completed": len(completed),
		"total": total,
		"percent": round(len(completed) / total * 100) if total else 100,
	}


def _availability(path: dict[str, Any], run: Any, capabilities: dict[str, Any]) -> dict[str, Any]:
	missing: list[str] = []
	missing_steps: list[str] = []
	for lesson_key, step in flatten_steps(path):
		configuration = step["configuration"]
		if step["verifier"] == "event_document_submitted" and not frappe.db.exists(
			"Scenario Event", {"scenario_run": run.name, "event_type": configuration["event_type"]}
		):
			missing.append(configuration["event_type"])
			missing_steps.append(f"{lesson_key}/{step['key']}")
		elif step["verifier"] == "capability_nonempty" and not capabilities.get(configuration["capability"]):
			missing.append(configuration["capability"])
			missing_steps.append(f"{lesson_key}/{step['key']}")
	return {
		"available": not missing,
		"missing": list(dict.fromkeys(missing)),
		"missing_steps": missing_steps,
		"message": None
		if not missing
		else _("This scenario does not contain: {0}").format(", ".join(dict.fromkeys(missing))),
	}


def _event(run: Any, event_type: str) -> Any | None:
	name = frappe.db.get_value(
		"Scenario Event",
		{"scenario_run": run.name, "event_type": event_type},
		"name",
		order_by="sequence asc",
	)
	return frappe.get_doc("Scenario Event", name) if name else None


def _event_document_submitted(run: Any, configuration: dict[str, Any]) -> dict[str, Any]:
	event = _event(run, configuration["event_type"])
	if not event:
		return _failed(_("The scenario has no {0} event.").format(configuration["event_type"]))
	docstatus = frappe.db.get_value(event.reference_doctype, event.reference_name, "docstatus")
	if int(docstatus or 0) != 1:
		return _failed(_("The linked ERPNext document is not submitted."))
	return _passed(
		_("Verified submitted {0} {1}.").format(event.reference_doctype, event.reference_name),
		doctype=event.reference_doctype,
		name=event.reference_name,
		route=_document_route(event.reference_doctype, event.reference_name),
	)


def _company_exists(run: Any, configuration: dict[str, Any]) -> dict[str, Any]:
	if not run.company or not frappe.db.exists("Company", run.company):
		return _failed(_("The scenario company is missing."))
	return _passed(
		_("Verified scenario company {0}.").format(run.company),
		doctype="Company",
		name=run.company,
		route=_document_route("Company", run.company),
	)


def _company_accounts_exist(run: Any, configuration: dict[str, Any]) -> dict[str, Any]:
	count = frappe.db.count("Account", {"company": run.company, "disabled": 0})
	return (
		_passed(_("Verified {0} active company accounts.").format(count), count=count)
		if count
		else _failed(_("No active accounts were found for the company."))
	)


def _capability_nonempty(run: Any, configuration: dict[str, Any]) -> dict[str, Any]:
	capabilities = json.loads(run.published_capabilities or "{}")
	entries = capabilities.get(configuration["capability"]) or []
	if not entries:
		return _failed(_("The scenario does not provide the required records."))
	entry = entries[0]
	name = entry.get("name") if isinstance(entry, dict) else str(entry)
	doctype = {
		"erpnext.parties.leads": "Lead",
		"erpnext.parties.customers": "Customer",
		"erpnext.parties.suppliers": "Supplier",
	}.get(configuration["capability"])
	return _passed(
		_("Verified {0} generated record(s).").format(len(entries)),
		doctype=doctype,
		name=name,
		route=_document_route(doctype, name) if doctype and name else None,
	)


def _party_links_exist(run: Any, configuration: dict[str, Any]) -> dict[str, Any]:
	manifest = load_manifest(run)
	counts = {doctype: 0 for doctype in ("Address", "Contact")}
	for record in manifest.created():
		if record.doctype in counts:
			counts[record.doctype] += 1
	if not all(counts.values()):
		return _failed(_("Scenario-owned contacts or addresses are missing."), counts=counts)
	return _passed(_("Verified {Address} addresses and {Contact} contacts.").format(**counts), counts=counts)


def _report_available(run: Any, configuration: dict[str, Any]) -> dict[str, Any]:
	report = configuration["report"]
	if not frappe.db.exists("Report", report):
		return _failed(_("ERPNext report {0} is unavailable.").format(report))
	return _passed(
		_("Verified ERPNext report {0}.").format(report),
		report=report,
		route=f"/app/query-report/{report.replace(' ', '%20')}",
	)


def _run_validation_passed(run: Any, configuration: dict[str, Any]) -> dict[str, Any]:
	summary = json.loads(run.validation_summary or "{}")
	if not summary.get("passed"):
		return _failed(_("Validate the Scenario Run successfully before completing this step."))
	return _passed(
		_("Scenario validation passed with no structural or accounting errors."), counts=summary.get("counts")
	)


def _return_source_exists(run: Any, configuration: dict[str, Any]) -> dict[str, Any]:
	event = _event(run, "Return / Credit Note")
	if not event:
		return _failed(_("The scenario has no return event."))
	doc = frappe.get_doc(event.reference_doctype, event.reference_name)
	source = doc.get("return_against")
	if not source or not frappe.db.exists(event.reference_doctype, source):
		return _failed(_("The return is not linked to an existing source document."))
	return _passed(
		_("Verified return link to {0}.").format(source),
		doctype=event.reference_doctype,
		name=source,
		route=_document_route(event.reference_doctype, source),
	)


def _fiscal_year_covers_run(run: Any, configuration: dict[str, Any]) -> dict[str, Any]:
	anchor = datetime.date.fromisoformat(str(run.anchor_date))
	name = frappe.db.get_value(
		"Fiscal Year",
		{"year_start_date": ["<=", anchor], "year_end_date": [">=", anchor], "disabled": 0},
		"name",
	)
	return (
		_passed(
			_("Verified fiscal year {0} covers the scenario.").format(name),
			doctype="Fiscal Year",
			name=name,
			route=_document_route("Fiscal Year", name),
		)
		if name
		else _failed(_("No active fiscal year covers the scenario anchor date."))
	)


def _doctype_available(run: Any, configuration: dict[str, Any]) -> dict[str, Any]:
	doctype = configuration["doctype"]
	return (
		_passed(_("Verified ERPNext DocType {0}.").format(doctype), doctype=doctype)
		if frappe.db.exists("DocType", doctype)
		else _failed(_("ERPNext DocType {0} is unavailable.").format(doctype))
	)


def _passed(message: str, **evidence: Any) -> dict[str, Any]:
	return {"passed": True, "message": message, "evidence": evidence}


def _failed(message: str, **evidence: Any) -> dict[str, Any]:
	return {"passed": False, "message": message, "evidence": evidence}


def _document_route(doctype: str, name: str) -> str:
	return f"/app/{frappe.scrub(doctype).replace('_', '-')}/{quote(str(name))}"


VERIFIERS: dict[str, Callable[[Any, dict[str, Any]], dict[str, Any]]] = {
	"company_exists": _company_exists,
	"company_accounts_exist": _company_accounts_exist,
	"event_document_submitted": _event_document_submitted,
	"capability_nonempty": _capability_nonempty,
	"party_links_exist": _party_links_exist,
	"report_available": _report_available,
	"run_validation_passed": _run_validation_passed,
	"return_source_exists": _return_source_exists,
	"fiscal_year_covers_run": _fiscal_year_covers_run,
	"doctype_available": _doctype_available,
}
