# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Safe installation guards."""

from __future__ import annotations

import frappe

from frappe_scenario.core.preflight import ERPNEXT_RECOVERY


def before_install() -> None:
	"""Stop before schema installation when ERPNext is absent from the Bench."""
	if "erpnext" in frappe.get_all_apps():
		return

	commands = "\n".join(f"  {command}" for command in ERPNEXT_RECOVERY)
	raise frappe.ValidationError(
		"ERPNext is not available in this Bench. Frappe Scenario does not fetch "
		f"repositories during installation.\nRun:\n{commands}"
	)
