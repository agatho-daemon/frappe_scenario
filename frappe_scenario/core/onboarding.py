# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Persisted, resumable onboarding state.

This service owns state transitions only. It never prompts, initializes
ERPNext, generates scenario data, or commits the database transaction.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import now_datetime

from frappe_scenario.core.preflight import BLOCKING, preflight_report

DOCTYPE = "Scenario Onboarding"
ROUTE = "/app/scenario-setup"

NEEDS_PREREQUISITES = "Needs Prerequisites"
NEEDS_SETUP = "Needs Setup"
NEEDS_SCENARIO = "Needs Scenario"
PREVIEW = "Preview"
GENERATING = "Generating"
READY = "Ready"
FAILED = "Failed"

STATES = (
	NEEDS_PREREQUISITES,
	NEEDS_SETUP,
	NEEDS_SCENARIO,
	PREVIEW,
	GENERATING,
	READY,
	FAILED,
)

TRANSITIONS = {
	NEEDS_PREREQUISITES: {NEEDS_SETUP, NEEDS_SCENARIO, FAILED},
	NEEDS_SETUP: {NEEDS_PREREQUISITES, NEEDS_SCENARIO, FAILED},
	NEEDS_SCENARIO: {NEEDS_SETUP, PREVIEW, FAILED},
	PREVIEW: {NEEDS_SCENARIO, GENERATING, FAILED},
	GENERATING: {READY, FAILED},
	READY: set(),
	FAILED: {NEEDS_PREREQUISITES, NEEDS_SETUP, NEEDS_SCENARIO, PREVIEW, GENERATING},
}


def ensure_onboarding(*, report: dict[str, Any] | None = None) -> Any:
	"""Create initial state once and return the singleton document.

	Repeated installation/synchronization must not reset human choices or
	progress. Only a record without ``initialized_on`` is initialized.
	"""
	doc = frappe.get_single(DOCTYPE)
	if doc.initialized_on:
		return doc

	report = report or preflight_report()
	doc.status = initial_state(report)
	doc.state_version = 1
	doc.initial_route_pending = 1
	doc.initialized_on = now_datetime()
	doc.last_preflight = _json(report)
	doc.progress = _json({"completed_steps": [], "current_state": doc.status})
	doc.save(ignore_permissions=True)
	return doc


def initial_state(report: dict[str, Any]) -> str:
	"""Resolve the first state from a read-only preflight report."""
	if report.get("summary", {}).get(BLOCKING):
		return NEEDS_PREREQUISITES

	setup = report.get("setup") or {}
	if (
		not report.get("erpnext", {}).get("installed")
		or not setup.get("complete")
		or not report.get("companies")
		or _has_configurable_setup_finding(report)
	):
		return NEEDS_SETUP
	return NEEDS_SCENARIO


def transition_onboarding(
	target: str,
	*,
	updates: dict[str, Any] | None = None,
	expected_version: int | None = None,
) -> Any:
	"""Move the singleton to an allowed state and persist supplied workflow data."""
	if target not in STATES:
		frappe.throw(_("Unknown onboarding state: {0}").format(target))
	if updates is not None and not isinstance(updates, dict):
		frappe.throw(_("Onboarding updates must be a JSON object."), frappe.ValidationError)

	doc = frappe.get_single(DOCTYPE)
	current = doc.status or NEEDS_PREREQUISITES
	if expected_version is not None and int(doc.state_version or 0) != int(expected_version):
		frappe.throw(
			_("Onboarding changed in another session. Refresh and try again."),
			frappe.TimestampMismatchError,
		)
	if target != current and target not in TRANSITIONS[current]:
		frappe.throw(
			_("Cannot move onboarding from {0} to {1}.").format(current, target),
			frappe.ValidationError,
		)

	for fieldname, value in (updates or {}).items():
		if fieldname not in editable_workflow_fields():
			frappe.throw(_("Onboarding field cannot be updated: {0}").format(fieldname))
		doc.set(
			fieldname, _json(value) if fieldname in json_fields() and not isinstance(value, str) else value
		)

	doc.status = target
	doc.state_version = int(doc.state_version or 0) + 1
	if target == READY and not doc.completed_on:
		doc.completed_on = now_datetime()
	if target != READY:
		doc.completed_on = None
	doc.save(ignore_permissions=True)
	return doc


def editable_workflow_fields() -> set[str]:
	return {
		"intent",
		"archetype",
		"depth",
		"scale",
		"setup_choices",
		"resolved_specification",
		"preview",
		"progress",
		"errors",
		"scenario_run",
		"last_preflight",
		"setup_approved",
		"setup_approved_by",
		"setup_approved_on",
	}


def json_fields() -> set[str]:
	return {
		"setup_choices",
		"resolved_specification",
		"preview",
		"progress",
		"errors",
		"last_preflight",
	}


def validate_transition(previous: str | None, target: str) -> None:
	"""Controller-level guard against bypassing the state service."""
	previous = previous or NEEDS_PREREQUISITES
	if target not in STATES:
		frappe.throw(_("Unknown onboarding state: {0}").format(target))
	if target != previous and target not in TRANSITIONS.get(previous, set()):
		frappe.throw(
			_("Cannot move onboarding from {0} to {1}.").format(previous, target),
			frappe.ValidationError,
		)


def _has_configurable_setup_finding(report: dict[str, Any]) -> bool:
	setup_keys = {
		"erpnext.installed",
		"erpnext.setup",
		"companies",
		"global_defaults",
		"fiscal_years",
		"chart_of_accounts",
	}
	return any(
		finding.get("key") in setup_keys and finding.get("classification") == "configurable"
		for finding in report.get("findings", [])
	)


def _json(value: Any) -> str:
	return json.dumps(value, indent="\t", sort_keys=True, default=str)
