# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""System Manager API for scenario-bound learning paths."""

from __future__ import annotations

import frappe

from frappe_scenario.core.learning import learning_home, restart_path, verify_step
from frappe_scenario.core.tutorial_runner import (
	advance_tutorial,
	exit_tutorial,
	restart_tutorial,
	start_tutorial,
	tutorial_state,
)


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


@frappe.whitelist()
def get_tutorial_state(run_name: str) -> dict:
	frappe.only_for("System Manager")
	return tutorial_state(run_name)


@frappe.whitelist(methods=["POST"])
def start_selling_tutorial(run_name: str) -> dict:
	frappe.only_for("System Manager")
	return start_tutorial(run_name)


@frappe.whitelist(methods=["POST"])
def advance_selling_tutorial(run_name: str) -> dict:
	frappe.only_for("System Manager")
	return advance_tutorial(run_name)


@frappe.whitelist(methods=["POST"])
def exit_selling_tutorial(run_name: str) -> dict:
	frappe.only_for("System Manager")
	return exit_tutorial(run_name)


@frappe.whitelist(methods=["POST"])
def restart_selling_tutorial(run_name: str) -> dict:
	frappe.only_for("System Manager")
	return restart_tutorial(run_name)
