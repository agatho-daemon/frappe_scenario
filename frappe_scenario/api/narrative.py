# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Read-only System Manager API for scenario narratives."""

from __future__ import annotations

import frappe

from frappe_scenario.core.narrative import explain_record as explain
from frappe_scenario.core.narrative import story_for_run


@frappe.whitelist()
def get_story(run_name: str) -> dict:
	frappe.only_for("System Manager")
	return story_for_run(run_name)


@frappe.whitelist()
def explain_record(run_name: str, doctype: str, name: str) -> dict:
	frappe.only_for("System Manager")
	return explain(run_name, doctype, name)
