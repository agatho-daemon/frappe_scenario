# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""System Manager API for the Troubleshooting Lab."""

import frappe

from frappe_scenario.core.troubleshooting import (
	activate_problem,
	check_diagnosis,
	lab_home,
	restore_case,
)


@frappe.whitelist()
def get_lab(run_name: str) -> dict:
	frappe.only_for("System Manager")
	return lab_home(run_name)


@frappe.whitelist(methods=["POST"])
def start_case(run_name: str, problem_key: str) -> dict:
	frappe.only_for("System Manager")
	return activate_problem(run_name, problem_key)


@frappe.whitelist(methods=["POST"])
def diagnose(case_name: str, diagnosis_key: str) -> dict:
	frappe.only_for("System Manager")
	return check_diagnosis(case_name, diagnosis_key)


@frappe.whitelist(methods=["POST"])
def restore(case_name: str) -> dict:
	frappe.only_for("System Manager")
	return restore_case(case_name)
