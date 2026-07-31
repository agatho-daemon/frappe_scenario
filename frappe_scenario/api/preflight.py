# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Read-only readiness API."""

from __future__ import annotations

from typing import Any

import frappe

from frappe_scenario.core.preflight import preflight_report


@frappe.whitelist()
def inspect() -> dict[str, Any]:
	"""Return the structured preflight report for a System Manager."""
	frappe.only_for("System Manager")
	return preflight_report()
