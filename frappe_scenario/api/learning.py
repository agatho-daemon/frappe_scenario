# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""System Manager API for scenario-bound learning paths."""

from __future__ import annotations

import frappe

from frappe_scenario.core.learning import learning_home, restart_path, verify_step


@frappe.whitelist()
def get_learning_home(run_name: str) -> dict:
	frappe.only_for("System Manager")
	return learning_home(run_name)


@frappe.whitelist(methods=["POST"])
def verify_lesson_step(
	run_name: str,
	path_key: str,
	lesson_key: str,
	step_key: str,
) -> dict:
	frappe.only_for("System Manager")
	return verify_step(run_name, path_key, lesson_key, step_key)


@frappe.whitelist(methods=["POST"])
def restart_learning_path(run_name: str, path_key: str) -> dict:
	frappe.only_for("System Manager")
	return restart_path(run_name, path_key)
