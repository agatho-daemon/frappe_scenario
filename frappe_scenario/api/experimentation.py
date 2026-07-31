# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""System Manager API for safe learner experimentation."""

import frappe

from frappe_scenario.core.experimentation import (
	create_checkpoint,
	describe_changes,
	list_checkpoints,
	reset_exercise,
	reset_module,
	restore_scenario,
)


@frappe.whitelist()
def get_changes(run_name: str, checkpoint_name: str | None = None) -> dict:
	frappe.only_for("System Manager")
	return describe_changes(run_name, checkpoint_name=checkpoint_name)


@frappe.whitelist()
def get_checkpoints(run_name: str) -> list[dict]:
	frappe.only_for("System Manager")
	return list_checkpoints(run_name)


@frappe.whitelist(methods=["POST"])
def save_checkpoint(run_name: str, label: str) -> dict:
	frappe.only_for("System Manager")
	return create_checkpoint(run_name, label)


@frappe.whitelist(methods=["POST"])
def reset_lesson(run_name: str, path_key: str, lesson_key: str) -> dict:
	frappe.only_for("System Manager")
	return reset_exercise(run_name, path_key, lesson_key)


@frappe.whitelist(methods=["POST"])
def reset_learning_module(run_name: str, path_key: str) -> dict:
	frappe.only_for("System Manager")
	return reset_module(run_name, path_key)


@frappe.whitelist(methods=["POST"])
def restore_checkpoint(run_name: str, checkpoint_name: str | None = None) -> dict:
	frappe.only_for("System Manager")
	return restore_scenario(run_name, checkpoint_name=checkpoint_name)
