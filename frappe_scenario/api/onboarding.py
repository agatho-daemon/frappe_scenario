# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""System Manager API for the shared onboarding state."""

from __future__ import annotations

import json
from typing import Any

import frappe

from frappe_scenario.core.bootstrap import execute_approved_bootstrap
from frappe_scenario.core.onboarding import (
	DOCTYPE,
	json_fields,
	transition_onboarding,
)
from frappe_scenario.core.quick_demo import generate_quick_demo
from frappe_scenario.core.setup_wizard import (
	approve_setup,
	save_choices,
	wizard_context,
)


@frappe.whitelist()
def get_state() -> dict[str, Any]:
	"""Return onboarding state with JSON fields decoded."""
	frappe.only_for("System Manager")
	return _serialize(frappe.get_single(DOCTYPE))


@frappe.whitelist(methods=["POST"])
def transition(
	target: str,
	expected_version: int,
	updates: str | dict[str, Any] | None = None,
) -> dict[str, Any]:
	"""Apply an optimistic, validated onboarding transition."""
	frappe.only_for("System Manager")
	if isinstance(updates, str):
		try:
			updates = json.loads(updates)
		except ValueError:
			frappe.throw("Onboarding updates must contain valid JSON.", frappe.ValidationError)
	return _serialize(transition_onboarding(target, updates=updates, expected_version=expected_version))


@frappe.whitelist()
def get_wizard() -> dict[str, Any]:
	"""Return the resumable wizard model for Desk."""
	frappe.only_for("System Manager")
	return wizard_context()


@frappe.whitelist(methods=["POST"])
def save_wizard_choices(
	choices: str | dict[str, Any],
	expected_version: int,
) -> dict[str, Any]:
	"""Validate and preview choices without applying ERPNext setup."""
	frappe.only_for("System Manager")
	if isinstance(choices, str):
		try:
			choices = json.loads(choices)
		except ValueError:
			frappe.throw("Onboarding choices must contain valid JSON.", frappe.ValidationError)
	return save_choices(choices, expected_version=int(expected_version))


@frappe.whitelist(methods=["POST"])
def approve_setup_plan(expected_version: int) -> dict[str, Any]:
	"""Record explicit setup approval without executing setup."""
	frappe.only_for("System Manager")
	return approve_setup(expected_version=int(expected_version))


@frappe.whitelist(methods=["POST"])
def initialize_erpnext(expected_version: int) -> dict[str, Any]:
	"""Apply an approved ERPNext foundation plan without generating scenario data."""
	frappe.only_for("System Manager")
	return execute_approved_bootstrap(expected_version=int(expected_version))


@frappe.whitelist(methods=["POST"])
def generate_quick_demo_run(
	expected_version: int,
	allow_non_disposable: int | bool = False,
) -> dict[str, Any]:
	"""Generate the approved Quick Demo through the normal scenario engine."""
	frappe.only_for("System Manager")
	return generate_quick_demo(
		expected_version=int(expected_version),
		allow_non_disposable=bool(int(allow_non_disposable)),
	)


def _serialize(doc: Any) -> dict[str, Any]:
	payload = doc.as_dict()
	for fieldname in json_fields():
		value = payload.get(fieldname)
		if value:
			try:
				payload[fieldname] = json.loads(value)
			except (TypeError, ValueError):
				pass
	return payload
