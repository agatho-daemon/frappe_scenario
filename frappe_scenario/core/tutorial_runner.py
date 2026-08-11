# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Focused, scenario-bound interactive tutorial runner.

This is deliberately a narrow selling proof of concept.  The built-in catalogue
is trusted application code; clients can select a run, but cannot submit routes,
selectors, verifier names, or executable expressions.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import now_datetime

from frappe_scenario.core.learning import (
	_completed,
	_progress,
	_progress_payload,
	_run,
	verify_step,
)
from frappe_scenario.core.learning_bindings import resolve_binding
from frappe_scenario.core.learning_catalog import (
	CATALOG_VERSION,
	STEP_TYPES,
	flatten_steps,
	get_path,
	step_contract,
)

PATH_KEY = "selling"
LESSON_KEY = "selling-complete-cycle"
ALLOWED_ACTIONS = STEP_TYPES


def tutorial_state(run_name: str, *, user: str | None = None) -> dict[str, Any]:
	"""Return the current trusted step and its scenario-resolved target."""
	run = _run(run_name)
	user = user or frappe.session.user
	path = get_path(PATH_KEY)
	steps = _tutorial_steps(path)
	progress = _progress(run.name, PATH_KEY, user, create=False)
	completed = _completed(progress)
	current = progress.current_step if progress else None
	step_id = current if current in {item[0] for item in steps} else _first_incomplete(steps, completed)
	step = next((candidate for candidate_id, candidate in steps if candidate_id == step_id), None)
	return {
		"tutorial": {
			"key": LESSON_KEY,
			"title": _("Order to cash"),
			"version": CATALOG_VERSION,
			"path_key": PATH_KEY,
		},
		"run": {"name": run.name, "title": run.title, "company": run.company},
		"active": bool(progress and progress.status == "In Progress" and step),
		"completed": bool(progress and progress.status == "Completed"),
		"progress": _progress_payload(progress, path) if progress else _empty_progress(len(steps)),
		"step": _step_payload(run, step_id, step, steps) if step else None,
	}


def start_tutorial(run_name: str, *, user: str | None = None) -> dict[str, Any]:
	run = _run(run_name)
	user = user or frappe.session.user
	path = get_path(PATH_KEY)
	steps = _tutorial_steps(path)
	progress = _progress(run.name, PATH_KEY, user, create=True)
	completed = _completed(progress)
	if progress.status != "Completed":
		progress.status = "In Progress"
		progress.started_at = progress.started_at or now_datetime()
		progress.current_step = _first_incomplete(steps, completed)
		progress.save(ignore_permissions=True)
	return tutorial_state(run.name, user=user)


def advance_tutorial(run_name: str, *, user: str | None = None) -> dict[str, Any]:
	"""Verify the current step on the server and advance only when it passes."""
	user = user or frappe.session.user
	state = tutorial_state(run_name, user=user)
	step = state.get("step")
	if not state["active"] or not step:
		return {**state, "passed": False, "message": _("Start or resume the tutorial first.")}
	result = verify_step(
		run_name,
		PATH_KEY,
		LESSON_KEY,
		step["key"],
		user=user,
	)
	return {**tutorial_state(run_name, user=user), "passed": result["passed"], "message": result["message"]}


def exit_tutorial(run_name: str, *, user: str | None = None) -> dict[str, Any]:
	"""Persist the current step; the client merely stops presenting it."""
	state = tutorial_state(run_name, user=user)
	state["active"] = False
	return state


def restart_tutorial(run_name: str, *, user: str | None = None) -> dict[str, Any]:
	from frappe_scenario.core.learning import restart_path

	restart_path(run_name, PATH_KEY, user=user)
	return start_tutorial(run_name, user=user)


def _tutorial_steps(path: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
	steps = [
		(f"{lesson_key}/{step['key']}", step)
		for lesson_key, step in flatten_steps(path)
		if lesson_key == LESSON_KEY and step["configuration"].get("tutorial")
	]
	if len(steps) != 10:
		raise frappe.ValidationError(_("The focused selling tutorial definition is incomplete."))
	return steps


def _first_incomplete(steps: list[tuple[str, dict[str, Any]]], completed: list[str]) -> str | None:
	return next((step_id for step_id, _step in steps if step_id not in completed), None)


def _step_payload(
	run: Any,
	step_id: str,
	step: dict[str, Any],
	steps: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
	contract = step_contract(step)
	action = contract["step_type"]
	if action not in ALLOWED_ACTIONS:
		raise frappe.ValidationError(_("Unsupported tutorial action."))
	target = resolve_binding(run, contract["binding"], fieldname=contract["fieldname"])
	position = next(
		index for index, (candidate_id, _candidate) in enumerate(steps, start=1) if candidate_id == step_id
	)
	return {
		"id": step_id,
		"key": step["key"],
		"title": step["title"],
		"action": action,
		"position": position,
		"total": len(steps),
		"target": target,
	}


def _empty_progress(total: int) -> dict[str, Any]:
	return {
		"status": "Not Started",
		"completed_steps": [],
		"current_step": None,
		"completed": 0,
		"total": total,
		"percent": 0,
	}
