# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""System Manager API for the shared onboarding state."""

from __future__ import annotations

import json
from typing import Any

import frappe

from frappe_scenario.core.onboarding import (
	DOCTYPE,
	json_fields,
	transition_onboarding,
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
