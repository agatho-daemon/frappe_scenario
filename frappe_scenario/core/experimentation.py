# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Safe, manifest-bounded learner checkpoints and resets."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import now_datetime

from frappe_scenario.core.canonical import VOLATILE_FIELDS
from frappe_scenario.core.engine import load_manifest
from frappe_scenario.core.learning_catalog import get_path

CHECKPOINT_DOCTYPE = "Scenario Checkpoint"
BASELINE_LABEL = "Generated baseline"


def ensure_baseline(run_name: str) -> str:
	"""Capture the generated state once; never silently replace it."""
	existing = frappe.db.get_value(
		CHECKPOINT_DOCTYPE,
		{"scenario_run": run_name, "checkpoint_type": "Baseline"},
		"name",
	)
	if existing:
		return existing
	return create_checkpoint(run_name, BASELINE_LABEL, checkpoint_type="Baseline")["name"]


def create_checkpoint(
	run_name: str,
	label: str,
	*,
	checkpoint_type: str = "Named",
	user: str | None = None,
) -> dict[str, Any]:
	run = _completed_run(run_name)
	label = (label or "").strip()
	if not label:
		frappe.throw(_("Give the checkpoint a name."), frappe.ValidationError)
	if checkpoint_type not in {"Baseline", "Named"}:
		frappe.throw(_("Unsupported checkpoint type."), frappe.ValidationError)
	if checkpoint_type == "Baseline" and frappe.db.exists(
		CHECKPOINT_DOCTYPE, {"scenario_run": run.name, "checkpoint_type": "Baseline"}
	):
		frappe.throw(_("This run already has a generated baseline."), frappe.DuplicateEntryError)

	snapshot = _capture(run)
	payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str)
	doc = frappe.get_doc(
		{
			"doctype": CHECKPOINT_DOCTYPE,
			"scenario_run": run.name,
			"checkpoint_label": label,
			"checkpoint_type": checkpoint_type,
			"user": user or frappe.session.user,
			"captured_at": now_datetime(),
			"record_count": len(snapshot["records"]),
			"snapshot_hash": hashlib.sha256(payload.encode()).hexdigest(),
			"snapshot_json": json.dumps(snapshot, indent="\t", default=str),
		}
	).insert(ignore_permissions=True)
	return _checkpoint_payload(doc)


def list_checkpoints(run_name: str) -> list[dict[str, Any]]:
	_completed_run(run_name)
	return [
		dict(row)
		for row in frappe.get_all(
			CHECKPOINT_DOCTYPE,
			filters={"scenario_run": run_name},
			fields=[
				"name",
				"checkpoint_label",
				"checkpoint_type",
				"user",
				"captured_at",
				"record_count",
				"snapshot_hash",
			],
			order_by="captured_at asc",
		)
	]


def describe_changes(run_name: str, *, checkpoint_name: str | None = None) -> dict[str, Any]:
	run = _completed_run(run_name)
	checkpoint = _checkpoint(run.name, checkpoint_name)
	baseline = json.loads(checkpoint.snapshot_json)
	current = _capture(run)
	changes = _diff(baseline, current)
	return {
		"run": run.name,
		"checkpoint": _checkpoint_payload(checkpoint),
		"scope_note": _(
			"This comparison covers scenario-owned records. Records you created independently are preserved and are not classified as scenario changes."
		),
		"counts": _change_counts(changes),
		"changes": changes,
	}


def reset_exercise(run_name: str, path_key: str, lesson_key: str) -> dict[str, Any]:
	return _reset(run_name, scope={"path_key": path_key, "lesson_key": lesson_key})


def reset_module(run_name: str, path_key: str) -> dict[str, Any]:
	return _reset(run_name, scope={"path_key": path_key})


def restore_scenario(
	run_name: str,
	*,
	checkpoint_name: str | None = None,
	reset_progress: bool = True,
) -> dict[str, Any]:
	return _reset(
		run_name,
		checkpoint_name=checkpoint_name,
		scope={},
		reset_progress=reset_progress,
	)


def _reset(
	run_name: str,
	*,
	scope: dict[str, str],
	checkpoint_name: str | None = None,
	reset_progress: bool = True,
) -> dict[str, Any]:
	run = _completed_run(run_name)
	checkpoint = _checkpoint(run.name, checkpoint_name)
	baseline = json.loads(checkpoint.snapshot_json)
	references = _scope_references(run, scope) if scope else set(baseline["records"])
	results: list[dict[str, Any]] = []
	blockers: list[dict[str, Any]] = []
	reset_savepoint = "scenario_experiment_reset"
	frappe.db.savepoint(reset_savepoint)

	for reference in sorted(references):
		saved = baseline["records"].get(reference)
		if not saved:
			continue
		result = _restore_record(reference, saved)
		(results if result["status"] in {"Restored", "Unchanged"} else blockers).append(result)

	if blockers:
		# A reset is atomic. Do not leave the learner with a half-restored module
		# when one record is deleted, cancelled, or externally constrained.
		frappe.db.rollback(save_point=reset_savepoint)
		results = []
	elif reset_progress:
		_reset_progress(run.name, scope)
	frappe.db.commit()
	return {
		"run": run.name,
		"checkpoint": checkpoint.name,
		"scope": scope or {"scenario": True},
		"restored": sum(result["status"] == "Restored" for result in results),
		"unchanged": sum(result["status"] == "Unchanged" for result in results),
		"blockers": blockers,
		"results": results,
	}


def _capture(run: Any) -> dict[str, Any]:
	manifest = load_manifest(run)
	records: dict[str, Any] = {}
	for record in manifest.created():
		if frappe.db.exists(record.doctype, record.name):
			doc = frappe.get_doc(record.doctype, record.name)
			records[record.reference] = {
				"doctype": record.doctype,
				"name": record.name,
				"docstatus": int(doc.docstatus),
				"values": _document_values(doc),
			}
		else:
			records[record.reference] = {
				"doctype": record.doctype,
				"name": record.name,
				"missing": True,
			}
	return {"version": "1.0", "run": run.name, "records": records}


def _document_values(doc: Any) -> dict[str, Any]:
	values: dict[str, Any] = {}
	for field in doc.meta.fields:
		if field.fieldname in VOLATILE_FIELDS or field.fieldtype in {
			"Section Break",
			"Column Break",
			"Tab Break",
			"HTML",
			"Button",
		}:
			continue
		value = doc.get(field.fieldname)
		if field.fieldtype == "Table":
			values[field.fieldname] = [
				{
					key: item
					for key, item in row.as_dict(convert_dates_to_str=True).items()
					if key not in VOLATILE_FIELDS and key not in {"parent", "parenttype", "parentfield"}
				}
				for row in (value or [])
			]
		else:
			values[field.fieldname] = _json_value(value)
	return values


def _json_value(value: Any) -> Any:
	return json.loads(json.dumps(value, default=str))


def _diff(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
	changes: list[dict[str, Any]] = []
	for reference in sorted(set(before["records"]) | set(after["records"])):
		old = before["records"].get(reference)
		new = after["records"].get(reference)
		if not old:
			changes.append({"reference": reference, "status": "Unowned Addition"})
		elif not new or new.get("missing"):
			changes.append({"reference": reference, "status": "Deleted"})
		elif old.get("missing"):
			changes.append({"reference": reference, "status": "Reappeared"})
		else:
			fields = sorted(
				field
				for field in set(old["values"]) | set(new["values"])
				if old["values"].get(field) != new["values"].get(field)
			)
			if old.get("docstatus") != new.get("docstatus"):
				fields.insert(0, "docstatus")
			if fields:
				changes.append({"reference": reference, "status": "Changed", "fields": fields})
	return changes


def _change_counts(changes: list[dict[str, Any]]) -> dict[str, int]:
	counts: dict[str, int] = {}
	for change in changes:
		counts[change["status"]] = counts.get(change["status"], 0) + 1
	return dict(sorted(counts.items()))


def _restore_record(reference: str, saved: dict[str, Any]) -> dict[str, Any]:
	doctype, name = reference.split("/", 1)
	if not frappe.db.exists(doctype, name):
		return _blocked(
			reference, "The scenario-owned record was deleted; it cannot be recreated safely in isolation."
		)
	doc = frappe.get_doc(doctype, name)
	if int(doc.docstatus) != int(saved["docstatus"]):
		return _blocked(
			reference,
			"Its Draft/Submitted/Cancelled state changed. Restore dependencies or regenerate the scenario.",
		)
	current = _document_values(doc)
	changed = [field for field in saved["values"] if current.get(field) != saved["values"].get(field)]
	if not changed:
		return {"reference": reference, "status": "Unchanged"}

	if int(doc.docstatus) == 1:
		not_allowed = [
			field
			for field in changed
			if not (doc.meta.get_field(field) and doc.meta.get_field(field).allow_on_submit)
		]
		if not_allowed:
			return _blocked(
				reference,
				"Submitted fields cannot be rewritten safely.",
				fields=not_allowed,
			)

	for field in changed:
		doc.set(field, saved["values"][field])
	savepoint = f"scenario_restore_{hashlib.sha1(reference.encode()).hexdigest()[:12]}"
	frappe.db.savepoint(savepoint)
	try:
		doc.save(ignore_permissions=True)
	except Exception as exception:
		frappe.db.rollback(save_point=savepoint)
		return _blocked(reference, _external_message(exception), fields=changed)
	return {"reference": reference, "status": "Restored", "fields": changed}


def _scope_references(run: Any, scope: dict[str, str]) -> set[str]:
	path = get_path(scope["path_key"])
	lessons = [
		lesson
		for lesson in path["lessons"]
		if not scope.get("lesson_key") or lesson["key"] == scope["lesson_key"]
	]
	if not lessons:
		frappe.throw(_("Unknown lesson for this learning path."), frappe.DoesNotExistError)
	manifest = load_manifest(run)
	capabilities: set[str] = set()
	references: set[str] = set()
	for lesson in lessons:
		for step in lesson["steps"]:
			configuration = step["configuration"]
			if configuration.get("capability"):
				capabilities.add(configuration["capability"])
			if configuration.get("event_type"):
				for event in frappe.get_all(
					"Scenario Event",
					filters={"scenario_run": run.name, "event_type": configuration["event_type"]},
					fields=["reference_doctype", "reference_name", "related_documents"],
				):
					references.add(f"{event.reference_doctype}/{event.reference_name}")
					for related in json.loads(event.related_documents or "[]"):
						references.add(f"{related['doctype']}/{related['name']}")
	if scope["path_key"] == "foundations":
		capabilities.update({"erpnext.foundation.company", "erpnext.foundation.accounts"})
	if scope["path_key"] == "crm-parties":
		capabilities.update(
			{"erpnext.parties.customers", "erpnext.parties.suppliers", "erpnext.parties.leads"}
		)
	for capability in capabilities:
		references.update(
			record.reference
			for record in manifest.for_capability(capability)
			if record.operation == "created"
		)
	owned = {record.reference for record in manifest.created()}
	return references & owned


def _reset_progress(run_name: str, scope: dict[str, str]) -> None:
	filters: dict[str, Any] = {"scenario_run": run_name}
	if scope.get("path_key"):
		filters["path_key"] = scope["path_key"]
	for name in frappe.get_all("Scenario Learner Progress", filters=filters, pluck="name"):
		progress = frappe.get_doc("Scenario Learner Progress", name)
		if scope.get("lesson_key"):
			prefix = f"{scope['lesson_key']}/"
			completed = [
				item for item in json.loads(progress.completed_steps or "[]") if not item.startswith(prefix)
			]
			progress.completed_steps = json.dumps(completed)
			progress.status = "In Progress" if completed else "Not Started"
			progress.current_step = None
			progress.completed_at = None
			progress.save(ignore_permissions=True)
		else:
			frappe.delete_doc(
				"Scenario Learner Progress", name, ignore_permissions=True, delete_permanently=True
			)


def _checkpoint(run_name: str, name: str | None) -> Any:
	name = name or frappe.db.get_value(
		CHECKPOINT_DOCTYPE,
		{"scenario_run": run_name, "checkpoint_type": "Baseline"},
		"name",
	)
	if not name:
		name = ensure_baseline(run_name)
	doc = frappe.get_doc(CHECKPOINT_DOCTYPE, name)
	if doc.scenario_run != run_name:
		frappe.throw(_("That checkpoint belongs to another Scenario Run."), frappe.PermissionError)
	return doc


def _completed_run(run_name: str) -> Any:
	run = frappe.get_doc("Scenario Run", run_name)
	run.check_permission("read")
	if run.status != "Completed":
		frappe.throw(_("Experimentation requires a completed Scenario Run."), frappe.ValidationError)
	return run


def _checkpoint_payload(doc: Any) -> dict[str, Any]:
	return {
		"name": doc.name,
		"label": doc.checkpoint_label,
		"type": doc.checkpoint_type,
		"user": doc.user,
		"captured_at": doc.captured_at,
		"record_count": doc.record_count,
		"snapshot_hash": doc.snapshot_hash,
	}


def _blocked(reference: str, message: str, **details: Any) -> dict[str, Any]:
	return {"reference": reference, "status": "Blocked", "message": message, **details}


def _external_message(exception: Exception) -> str:
	return _("Frappe refused the reset, usually because another record depends on this one: {0}").format(
		str(exception)
	)
