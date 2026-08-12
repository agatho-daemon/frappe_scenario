# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""System Manager API for scenario-bound learning paths."""

from __future__ import annotations

import frappe

from frappe_scenario.core.learning import learning_home, restart_path, verify_step
from frappe_scenario.core.learning_catalog import PATHS
from frappe_scenario.core.learning_portal import LEARNER_ROLES, enroll, path_eligibility, training_home
from frappe_scenario.core.tutorial_runner import (
	advance_tutorial,
	exit_tutorial,
	restart_tutorial,
	start_tutorial,
	tutorial_state,
)


def _only_for_learner() -> None:
	if not set(frappe.get_roles()) & LEARNER_ROLES:
		raise frappe.PermissionError("An ERPNext learning role is required.")


@frappe.whitelist()
def get_training_home() -> dict:
	_only_for_learner()
	return training_home()


@frappe.whitelist(methods=["POST"])
def enroll_learning_path(run_name: str, path_key: str) -> dict:
	_only_for_learner()
	return enroll(run_name, path_key)


@frappe.whitelist(methods=["POST"])
def assign_learning_path(run_name: str, path_key: str, user: str) -> dict:
	frappe.only_for("System Manager")
	return enroll(run_name, path_key, user=user, assigned_by=frappe.session.user)


@frappe.whitelist()
def get_learning_home(run_name: str) -> dict:
	_only_for_learner()
	return learning_home(run_name)


@frappe.whitelist(methods=["POST"])
def verify_lesson_step(
	run_name: str,
	path_key: str,
	lesson_key: str,
	step_key: str,
) -> dict:
	_only_for_learner()
	run = frappe.get_doc("Scenario Run", run_name)
	path = next(candidate for candidate in PATHS if candidate["key"] == path_key)
	eligibility = path_eligibility(run, path, user=frappe.session.user)
	if not eligibility["eligible"]:
		raise frappe.PermissionError(" ".join(eligibility["reasons"]))
	return verify_step(run_name, path_key, lesson_key, step_key)


@frappe.whitelist(methods=["POST"])
def restart_learning_path(run_name: str, path_key: str) -> dict:
	_only_for_learner()
	return restart_path(run_name, path_key)


@frappe.whitelist()
def get_tutorial_state(run_name: str) -> dict:
	_only_for_learner()
	return tutorial_state(run_name)


@frappe.whitelist(methods=["POST"])
def start_selling_tutorial(run_name: str) -> dict:
	_only_for_learner()
	return start_tutorial(run_name)


@frappe.whitelist(methods=["POST"])
def advance_selling_tutorial(run_name: str) -> dict:
	_only_for_learner()
	return advance_tutorial(run_name)


@frappe.whitelist(methods=["POST"])
def exit_selling_tutorial(run_name: str) -> dict:
	_only_for_learner()
	return exit_tutorial(run_name)


@frappe.whitelist(methods=["POST"])
def restart_selling_tutorial(run_name: str) -> dict:
	_only_for_learner()
	return restart_tutorial(run_name)
