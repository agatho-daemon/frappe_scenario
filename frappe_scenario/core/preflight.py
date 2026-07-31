# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Read-only site readiness assessment.

Preflight deliberately performs no setup and writes no records. Its structured
result is shared by the CLI, API, and the future onboarding clients.
"""

from __future__ import annotations

import datetime
import importlib
from typing import Any

import frappe

from frappe_scenario.core.safety import site_safety_report

READY = "ready"
CONFIGURABLE = "configurable"
BLOCKING = "blocking"
DESTRUCTIVE_RISK = "destructive-risk"
CLASSIFICATIONS = (READY, CONFIGURABLE, BLOCKING, DESTRUCTIVE_RISK)

ERPNEXT_RECOVERY = [
	"bench get-app erpnext",
	"bench install-app erpnext",
	"bench install-app frappe_scenario",
]

BUSINESS_DOCTYPES = (
	"Customer",
	"Supplier",
	"Lead",
	"Contact",
	"Address",
	"Item",
	"Sales Order",
	"Delivery Note",
	"Sales Invoice",
	"Purchase Order",
	"Purchase Receipt",
	"Purchase Invoice",
	"Payment Entry",
	"Journal Entry",
	"GL Entry",
	"Stock Ledger Entry",
)


def preflight_report() -> dict[str, Any]:
	"""Return the current site's readiness without mutating it."""
	all_apps = set(frappe.get_all_apps())
	installed_apps = set(frappe.get_installed_apps())
	erpnext_available = "erpnext" in all_apps
	erpnext_installed = "erpnext" in installed_apps
	findings: list[dict[str, Any]] = []

	_add_erpnext_findings(findings, erpnext_available, erpnext_installed)
	versions = _versions(all_apps, installed_apps)
	safety = site_safety_report()
	setup = _setup_state(erpnext_installed)
	companies = _companies() if erpnext_installed else []
	global_defaults = _global_defaults(erpnext_installed)
	fiscal_years = _fiscal_years() if erpnext_installed else []
	accounts = _account_state(companies) if erpnext_installed else _empty_account_state()
	stock = _stock_state(companies) if erpnext_installed else {}
	organization = _organization_state() if erpnext_installed else {"warehouses": [], "cost_centers": []}
	existing_data = _existing_business_data(erpnext_installed)

	_add_setup_findings(
		findings, erpnext_installed, setup, companies, global_defaults, fiscal_years, accounts
	)
	_add_safety_findings(findings, safety)
	_add_existing_data_findings(findings, existing_data)

	counts = {classification: 0 for classification in CLASSIFICATIONS}
	for finding in findings:
		counts[finding["classification"]] += 1

	return {
		"generated_at": datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
		"site": frappe.local.site,
		"status": _overall_status(counts),
		"summary": counts,
		"findings": findings,
		"environment": {
			"versions": versions,
			"bench_apps": sorted(all_apps),
			"installed_apps": sorted(installed_apps),
		},
		"erpnext": {
			"checkout_available": erpnext_available,
			"installed": erpnext_installed,
			"recovery_commands": ERPNEXT_RECOVERY if not erpnext_available else [],
		},
		"setup": setup,
		"companies": companies,
		"global_defaults": global_defaults,
		"fiscal_years": fiscal_years,
		"chart_of_accounts": accounts,
		"stock": stock,
		"organization": organization,
		"safety": safety,
		"existing_business_data": existing_data,
	}


def _finding(
	findings: list[dict[str, Any]],
	key: str,
	classification: str,
	message: str,
	*,
	value: Any = None,
	remediation: str | list[str] | None = None,
) -> None:
	entry = {
		"key": key,
		"classification": classification,
		"message": message,
		"value": value,
	}
	if remediation:
		entry["remediation"] = remediation
	findings.append(entry)


def _add_erpnext_findings(findings: list[dict[str, Any]], available: bool, installed: bool) -> None:
	if not available:
		_finding(
			findings,
			"erpnext.checkout",
			BLOCKING,
			"ERPNext is absent from this Bench; Frappe Scenario will not fetch repositories.",
			value=False,
			remediation=ERPNEXT_RECOVERY,
		)
	elif not installed:
		_finding(
			findings,
			"erpnext.installed",
			CONFIGURABLE,
			"ERPNext is available in the Bench but is not installed on this site.",
			value=False,
			remediation="bench install-app frappe_scenario",
		)
	else:
		_finding(findings, "erpnext.installed", READY, "ERPNext is installed.", value=True)


def _add_setup_findings(
	findings: list[dict[str, Any]],
	erpnext_installed: bool,
	setup: dict[str, Any],
	companies: list[dict[str, Any]],
	defaults: dict[str, Any],
	fiscal_years: list[dict[str, Any]],
	accounts: dict[str, Any],
) -> None:
	if not erpnext_installed:
		return

	_finding(
		findings,
		"erpnext.setup",
		READY if setup["complete"] else CONFIGURABLE,
		"ERPNext setup is complete." if setup["complete"] else "ERPNext setup is incomplete.",
		value=setup["complete"],
	)
	_finding(
		findings,
		"companies",
		READY if companies else CONFIGURABLE,
		f"{len(companies)} compan{'y' if len(companies) == 1 else 'ies'} found."
		if companies
		else "No company is configured.",
		value=len(companies),
	)

	missing_defaults = [
		key for key in ("company", "country", "currency", "language", "timezone") if not defaults.get(key)
	]
	_finding(
		findings,
		"global_defaults",
		READY if not missing_defaults else CONFIGURABLE,
		"Global locale and company defaults are complete."
		if not missing_defaults
		else f"Global defaults are missing: {', '.join(missing_defaults)}.",
		value=defaults,
	)
	_finding(
		findings,
		"fiscal_years",
		READY if any(not year.get("disabled") for year in fiscal_years) else CONFIGURABLE,
		f"{len(fiscal_years)} fiscal year(s) found, "
		f"{sum(not year.get('disabled') for year in fiscal_years)} active."
		if fiscal_years
		else "No active fiscal year is configured.",
		value={
			"total": len(fiscal_years),
			"active": sum(not year.get("disabled") for year in fiscal_years),
		},
	)
	_finding(
		findings,
		"chart_of_accounts",
		READY if accounts["total"] else CONFIGURABLE,
		f"{accounts['total']} accounts found; numbering mode is {accounts['numbering_mode']}."
		if accounts["total"]
		else "No Chart of Accounts is configured.",
		value=accounts,
	)


def _add_safety_findings(findings: list[dict[str, Any]], safety: dict[str, Any]) -> None:
	_finding(
		findings,
		"site.developer_mode",
		READY if safety["developer_mode"] else CONFIGURABLE,
		"Developer mode is enabled." if safety["developer_mode"] else "Developer mode is disabled.",
		value=safety["developer_mode"],
	)
	_finding(
		findings,
		"site.disposable",
		READY if safety["disposable"] else CONFIGURABLE,
		"Site is explicitly marked disposable."
		if safety["disposable"]
		else "Site is not marked as a disposable scenario target.",
		value=safety["disposable"],
	)
	_finding(
		findings,
		"site.maintenance_mode",
		BLOCKING if safety["maintenance_mode"] else READY,
		"The site is in maintenance mode; scenario generation is blocked."
		if safety["maintenance_mode"]
		else "The site is not in maintenance mode.",
		value=safety["maintenance_mode"],
		remediation="Use a disposable development site." if safety["maintenance_mode"] else None,
	)


def _add_existing_data_findings(findings: list[dict[str, Any]], existing_data: dict[str, Any]) -> None:
	total = existing_data["total"]
	_finding(
		findings,
		"existing_business_data",
		DESTRUCTIVE_RISK if total else READY,
		f"Existing site contains {total} business/ledger records; reuse requires explicit review."
		if total
		else "No existing business or ledger records were detected.",
		value=existing_data,
	)


def _versions(all_apps: set[str], installed_apps: set[str]) -> dict[str, dict[str, Any]]:
	versions: dict[str, dict[str, Any]] = {}
	for app in ("frappe", "erpnext", "frappe_scenario"):
		available = app == "frappe" or app in all_apps
		version = None
		if available:
			try:
				version = str(getattr(importlib.import_module(app), "__version__", "unknown"))
			except ImportError:
				available = False
		versions[app] = {
			"version": version,
			"checkout_available": available,
			"installed_on_site": app == "frappe" or app in installed_apps,
		}
	return versions


def _setup_state(erpnext_installed: bool) -> dict[str, Any]:
	if not erpnext_installed:
		return {"complete": False, "applications": {}}

	applications: dict[str, bool] = {}
	if frappe.db.table_exists("Installed Application"):
		for row in frappe.get_all(
			"Installed Application",
			filters={"app_name": ("in", ["frappe", "erpnext"])},
			fields=["app_name", "is_setup_complete"],
		):
			applications[row.app_name] = bool(row.is_setup_complete)
	complete = bool(frappe.is_setup_complete()) and all(
		applications.get(app, False) for app in ("frappe", "erpnext")
	)
	return {"complete": complete, "applications": applications}


def _companies() -> list[dict[str, Any]]:
	fields = [
		"name",
		"abbr",
		"country",
		"default_currency",
		"enable_perpetual_inventory",
		"is_group",
	]
	return [dict(row) for row in frappe.get_all("Company", fields=fields, order_by="name")]


def _global_defaults(erpnext_installed: bool) -> dict[str, Any]:
	system = _single_values("System Settings", ("country", "language", "time_zone"))
	erpnext = (
		_single_values("Global Defaults", ("default_company", "country", "default_currency"))
		if erpnext_installed
		else {}
	)
	return {
		"company": erpnext.get("default_company"),
		"country": erpnext.get("country") or system.get("country"),
		"currency": erpnext.get("default_currency"),
		"language": system.get("language"),
		"timezone": system.get("time_zone"),
	}


def _fiscal_years() -> list[dict[str, Any]]:
	return [
		dict(row)
		for row in frappe.get_all(
			"Fiscal Year",
			fields=["name", "year_start_date", "year_end_date", "disabled"],
			order_by="year_start_date",
		)
	]


def _empty_account_state() -> dict[str, Any]:
	return {
		"total": 0,
		"groups": 0,
		"ledgers": 0,
		"numbered": 0,
		"unnumbered": 0,
		"numbering_mode": "empty",
		"by_company": {},
	}


def _account_state(companies: list[dict[str, Any]]) -> dict[str, Any]:
	state = _empty_account_state()
	for company in companies:
		name = company["name"]
		total = frappe.db.count("Account", {"company": name})
		groups = frappe.db.count("Account", {"company": name, "is_group": 1})
		numbered = frappe.db.count(
			"Account", {"company": name, "is_group": 0, "account_number": ("is", "set")}
		)
		ledgers = max(total - groups, 0)
		unnumbered = max(ledgers - numbered, 0)
		state["by_company"][name] = {
			"total": total,
			"groups": groups,
			"ledgers": ledgers,
			"numbered": numbered,
			"unnumbered": unnumbered,
		}
		state["total"] += total
		state["groups"] += groups
		state["ledgers"] += ledgers
		state["numbered"] += numbered
		state["unnumbered"] += unnumbered

	if not state["total"]:
		state["numbering_mode"] = "empty"
	elif state["numbered"] and state["unnumbered"]:
		state["numbering_mode"] = "mixed"
	elif state["numbered"]:
		state["numbering_mode"] = "numbered"
	else:
		state["numbering_mode"] = "unnumbered"
	return state


def _stock_state(companies: list[dict[str, Any]]) -> dict[str, Any]:
	settings = _single_values(
		"Stock Settings",
		(
			"valuation_method",
			"allow_negative_stock",
			"default_warehouse",
			"stock_uom",
		),
	)
	settings["companies"] = {
		company["name"]: {
			"perpetual_inventory": bool(company.get("enable_perpetual_inventory")),
		}
		for company in companies
	}
	return settings


def _organization_state() -> dict[str, list[dict[str, Any]]]:
	return {
		"warehouses": [
			dict(row)
			for row in frappe.get_all(
				"Warehouse",
				filters={"disabled": 0},
				fields=["name", "warehouse_name", "company", "is_group", "disabled"],
				order_by="company, name",
			)
		],
		"cost_centers": [
			dict(row)
			for row in frappe.get_all(
				"Cost Center",
				filters={"disabled": 0},
				fields=["name", "cost_center_name", "company", "is_group", "disabled"],
				order_by="company, name",
			)
		],
	}


def _existing_business_data(erpnext_installed: bool) -> dict[str, Any]:
	if not erpnext_installed:
		return {"total": 0, "counts": {}}
	counts = {doctype: frappe.db.count(doctype) for doctype in BUSINESS_DOCTYPES}
	return {"total": sum(counts.values()), "counts": counts}


def _single_values(doctype: str, fields: tuple[str, ...]) -> dict[str, Any]:
	return {field: frappe.db.get_single_value(doctype, field) for field in fields}


def _overall_status(counts: dict[str, int]) -> str:
	for classification in (BLOCKING, DESTRUCTIVE_RISK, CONFIGURABLE):
		if counts[classification]:
			return classification
	return READY
