# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Run lifecycle endpoints."""

from __future__ import annotations

import json
from typing import Any

import frappe

from frappe_scenario.core import engine
from frappe_scenario.core.specification import load_specification, validate_schema

ROLE = "System Manager"


@frappe.whitelist()
def validate_spec(specification: str | dict[str, Any]) -> dict[str, Any]:
	"""Check a specification against the schema. Touches nothing."""
	frappe.only_for(ROLE)
	parsed = load_specification(specification)
	problems = validate_schema(parsed)
	return {
		"valid": not problems,
		"problems": problems,
		"schema_version": parsed.get("schema_version"),
	}


@frappe.whitelist()
def plan(specification: str | dict[str, Any]) -> dict[str, Any]:
	"""Describe what a specification would create. Writes nothing."""
	frappe.only_for(ROLE)
	return engine.plan(specification)


@frappe.whitelist()
def create_run(
	specification: str | dict[str, Any],
	title: str | None = None,
	definition: str | None = None,
) -> dict[str, Any]:
	"""Persist a run without approving or executing it."""
	frappe.only_for(ROLE)
	run_name = engine.create_run(specification, title=title, definition=definition)
	return engine.get_status(run_name)


@frappe.whitelist()
def approve_run(run_name: str) -> dict[str, Any]:
	"""Record human approval. Generation is impossible without it."""
	frappe.only_for(ROLE)
	return engine.approve_run(run_name)


@frappe.whitelist()
def run(run_name: str, background: bool = True) -> dict[str, Any]:
	"""Execute an approved run, on the long queue by default."""
	frappe.only_for(ROLE)
	if frappe.parse_json(background) if isinstance(background, str) else background:
		return engine.enqueue_run(run_name)
	return engine.execute_run(run_name)


@frappe.whitelist()
def resume(run_name: str) -> dict[str, Any]:
	frappe.only_for(ROLE)
	return engine.resume_run(run_name)


@frappe.whitelist()
def get_status(run_name: str) -> dict[str, Any]:
	frappe.only_for(ROLE)
	return engine.get_status(run_name)


@frappe.whitelist()
def validate_run(run_name: str) -> dict[str, Any]:
	frappe.only_for(ROLE)
	return engine.validate_run(run_name)


@frappe.whitelist()
def cleanup(run_name: str) -> dict[str, Any]:
	frappe.only_for(ROLE)
	return engine.cleanup_run(run_name)


@frappe.whitelist()
def export(run_name: str) -> dict[str, Any]:
	frappe.only_for(ROLE)
	return engine.export_run(run_name)


@frappe.whitelist()
def propose_repair(run_name: str) -> dict[str, Any]:
	"""Turn validation failures into concrete, reviewable specification changes.

	This only suggests. Nothing is applied until a person calls
	:func:`apply_repair`, which creates a new run rather than mutating this one.
	"""
	frappe.only_for(ROLE)
	run_doc = frappe.get_doc(engine.RUN_DOCTYPE, run_name)
	summary = json.loads(run_doc.validation_summary or "{}")
	specification = json.loads(run_doc.specification)

	proposals: list[dict[str, Any]] = []
	for issue in summary.get("issues", []):
		if issue.get("severity") == "info":
			continue
		change = _repair_for(issue, specification)
		if change:
			proposals.append(change)

	return {
		"run_id": run_doc.name,
		"specification": specification,
		"proposals": proposals,
		"unrepairable": [
			issue
			for issue in summary.get("issues", [])
			if issue.get("severity") == "error" and not _repair_for(issue, specification)
		],
	}


@frappe.whitelist()
def apply_repair(run_name: str, proposals: str | list[dict[str, Any]]) -> dict[str, Any]:
	"""Create a new draft run with the chosen repairs applied.

	The original run is left untouched so the failing dataset stays available
	for inspection.
	"""
	frappe.only_for(ROLE)
	selected = frappe.parse_json(proposals) if isinstance(proposals, str) else proposals
	run_doc = frappe.get_doc(engine.RUN_DOCTYPE, run_name)
	specification = json.loads(run_doc.specification)

	applied: list[dict[str, Any]] = []
	for proposal in selected:
		path = proposal.get("path")
		if not path:
			continue
		_set_path(specification, path, proposal["value"])
		applied.append({"path": path, "value": proposal["value"], "rule": proposal.get("rule")})

	new_run = engine.create_run(
		specification,
		title=f"{run_doc.title} (repair of {run_doc.name})",
		definition=run_doc.scenario_definition,
	)
	return {"run_id": new_run, "repaired_from": run_doc.name, "applied": applied}


#: Validation rules that map to a specific, safe specification change.
_REPAIRS: dict[str, tuple[str, Any]] = {
	"erpnext.selling.customer_concentration": ("parties.customers", "increase"),
	"stock.non_negative": ("providers.erpnext\\.opening.months_of_cover", "increase"),
	"plausibility.activity_present": ("operations.sales_orders_per_month", "increase"),
	"erpnext.payments.overdue_profile": ("accounting.customer_payment_ratio", "decrease"),
}


def _repair_for(issue: dict[str, Any], specification: dict[str, Any]) -> dict[str, Any] | None:
	repair = _REPAIRS.get(issue.get("rule") or "")
	if not repair:
		return None

	path, direction = repair
	current = _get_path(specification, path)
	if current is None:
		return None

	if isinstance(current, int):
		value = max(current + 1, round(current * 1.5)) if direction == "increase" else max(1, current // 2)
	elif isinstance(current, float):
		value = round(current * 1.25, 4) if direction == "increase" else round(current * 0.75, 4)
	else:
		return None

	return {
		"rule": issue["rule"],
		"path": path,
		"current": current,
		"value": value,
		"reason": issue.get("remediation") or issue.get("message"),
	}


def _split(path: str) -> list[str]:
	"""Split a dotted path, honouring ``\\.`` as a literal dot in a key."""
	parts: list[str] = []
	current = ""
	escaped = False
	for character in path:
		if escaped:
			current += character
			escaped = False
		elif character == "\\":
			escaped = True
		elif character == ".":
			parts.append(current)
			current = ""
		else:
			current += character
	parts.append(current)
	return parts


def _get_path(payload: dict[str, Any], path: str) -> Any:
	cursor: Any = payload
	for part in _split(path):
		if not isinstance(cursor, dict):
			return None
		cursor = cursor.get(part)
	return cursor


def _set_path(payload: dict[str, Any], path: str, value: Any) -> None:
	parts = _split(path)
	cursor = payload
	for part in parts[:-1]:
		cursor = cursor.setdefault(part, {})
	cursor[parts[-1]] = value
