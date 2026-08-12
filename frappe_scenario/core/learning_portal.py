# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Server-side discovery, eligibility, and lightweight learning assignment."""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import now_datetime

from frappe_scenario.core.learning import _progress
from frappe_scenario.core.learning_catalog import CATALOG_VERSION, PATHS, flatten_steps

LEARNER_ROLES = {
	"System Manager",
	"Accounts User",
	"Sales User",
	"Purchase User",
	"Stock User",
	"Sales Manager",
	"Purchase Manager",
	"Stock Manager",
	"Accounts Manager",
}

MODULE_ROLES = {
	"Foundations": LEARNER_ROLES,
	"CRM": {"System Manager", "Sales User", "Sales Manager"},
	"Buying": {"System Manager", "Purchase User", "Purchase Manager", "Accounts User", "Accounts Manager"},
	"Selling": {"System Manager", "Sales User", "Sales Manager", "Accounts User", "Accounts Manager"},
	"Stock": {"System Manager", "Stock User", "Stock Manager"},
	"Accounting": {"System Manager", "Accounts User", "Accounts Manager"},
}

MODULE_DOCTYPES = {
	"Foundations": {"Company", "Account"},
	"CRM": {"Lead", "Customer", "Supplier", "Contact", "Address"},
	"Buying": {"Purchase Order", "Purchase Receipt", "Purchase Invoice"},
	"Selling": {"Sales Order", "Delivery Note", "Sales Invoice"},
	"Stock": {"Item", "Warehouse", "Stock Ledger Entry"},
	"Accounting": {"GL Entry", "Payment Entry", "Journal Entry"},
}

PATH_PREREQUISITES = {
	"returns": ("selling",),
	"reports": ("accounting",),
	"period-closing": ("accounting",),
}


def training_home(*, user: str | None = None) -> dict[str, Any]:
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	if not roles & LEARNER_ROLES:
		raise frappe.PermissionError(_("You do not have an ERPNext learning role."))
	runs = frappe.get_all(
		"Scenario Run",
		filters={"status": "Completed"},
		fields=["name", "title", "company", "archetype", "scale", "status", "finished_at"],
		order_by="finished_at desc",
		limit_page_length=50,
	)
	progress_rows = frappe.get_all(
		"Scenario Learner Progress",
		filters={"user": user},
		fields=[
			"name",
			"scenario_run",
			"path_key",
			"path_version",
			"status",
			"completed_steps",
			"started_at",
			"completed_at",
			"assigned_by",
			"assigned_at",
		],
		limit_page_length=500,
	)
	progress = {(row.scenario_run, row.path_key): row for row in progress_rows}
	cards = []
	for run in runs:
		paths = []
		for path in PATHS:
			eligibility = path_eligibility(run, path, user=user, roles=roles, progress=progress)
			row = progress.get((run.name, path["key"]))
			completed = len(json.loads(row.completed_steps or "[]")) if row else 0
			total = len(flatten_steps(path))
			paths.append(
				{
					"key": path["key"],
					"title": path["title"],
					"module": path["module"],
					"version": CATALOG_VERSION,
					"status": row.status if row else "Available",
					"assigned": bool(row),
					"assigned_by": row.assigned_by if row else None,
					"completed": completed,
					"total": total,
					"percent": round(completed / total * 100) if total else 100,
					"eligibility": eligibility,
				}
			)
		if any(path["eligibility"]["eligible"] or path["assigned"] for path in paths):
			cards.append({**run, "paths": paths})
	return {
		"user": user,
		"runs": cards,
		"summary": {
			"available": sum(
				path["status"] == "Available" and path["eligibility"]["eligible"]
				for run in cards
				for path in run["paths"]
			),
			"active": sum(path["status"] == "In Progress" for run in cards for path in run["paths"]),
			"completed": sum(path["status"] == "Completed" for run in cards for path in run["paths"]),
			"assigned": sum(path["assigned"] for run in cards for path in run["paths"]),
		},
	}


def path_eligibility(
	run: Any,
	path: dict[str, Any],
	*,
	user: str,
	roles: set[str] | None = None,
	progress: dict[tuple[str, str], Any] | None = None,
) -> dict[str, Any]:
	roles = roles or set(frappe.get_roles(user))
	reasons = []
	if run.status != "Completed":
		reasons.append(_("The Scenario Run is not completed."))
	if not run.company or not frappe.db.exists("Company", run.company):
		reasons.append(_("The scenario company is unavailable."))
	if "erpnext" not in frappe.get_installed_apps():
		reasons.append(_("ERPNext is not installed on this site."))
	missing_doctypes = sorted(
		doctype
		for doctype in MODULE_DOCTYPES.get(path["module"], set())
		if not frappe.db.exists("DocType", doctype)
	)
	if missing_doctypes:
		reasons.append(_("Required ERPNext records are unavailable: {0}").format(", ".join(missing_doctypes)))
	required_roles = MODULE_ROLES.get(path["module"], LEARNER_ROLES)
	if not roles & required_roles:
		reasons.append(_("Your roles do not include this ERPNext module."))
	default_company = frappe.defaults.get_user_default("Company", user=user)
	if default_company and default_company != run.company and "System Manager" not in roles:
		reasons.append(_("This scenario does not match your default company."))
	allowed_companies = set(
		frappe.get_all(
			"User Permission",
			filters={"user": user, "allow": "Company"},
			pluck="for_value",
		)
	)
	if allowed_companies and run.company not in allowed_companies and "System Manager" not in roles:
		reasons.append(_("Your Company permissions do not include this scenario."))
	row = (progress or {}).get((run.name, path["key"]))
	if row and row.path_version != CATALOG_VERSION:
		reasons.append(_("This assignment uses an older lesson version and must be restarted."))
	for prerequisite in PATH_PREREQUISITES.get(path["key"], ()):
		prerequisite_progress = (progress or {}).get((run.name, prerequisite))
		if not prerequisite_progress or prerequisite_progress.status != "Completed":
			reasons.append(
				_("Complete {0} before starting this path.").format(prerequisite.replace("-", " ").title())
			)
	return {"eligible": not reasons, "reasons": reasons, "required_roles": sorted(required_roles)}


def enroll(
	run_name: str, path_key: str, *, user: str | None = None, assigned_by: str | None = None
) -> dict[str, Any]:
	user = user or frappe.session.user
	run = frappe.get_doc("Scenario Run", run_name)
	path = next((candidate for candidate in PATHS if candidate["key"] == path_key), None)
	if not path:
		raise frappe.DoesNotExistError(_("Unknown learning path."))
	eligibility = path_eligibility(run, path, user=user)
	if not eligibility["eligible"]:
		raise frappe.PermissionError(" ".join(eligibility["reasons"]))
	progress = _progress(run.name, path_key, user, create=True)
	if not progress.assigned_at:
		progress.assigned_at = now_datetime()
		progress.assigned_by = assigned_by or frappe.session.user
		progress.save(ignore_permissions=True)
	return {"progress": progress.name, "run": run.name, "path_key": path_key, "status": progress.status}
