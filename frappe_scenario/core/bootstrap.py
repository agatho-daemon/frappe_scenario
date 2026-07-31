# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Idempotent, explicitly approved ERPNext foundation bootstrap.

This module changes only the missing or explicitly selected foundations needed
by onboarding. Normal Frappe and ERPNext document controllers remain
authoritative. Every pre-existing setting changed here is recorded with its
prior value in the onboarding bootstrap manifest.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import add_days, add_years, getdate, now_datetime

from frappe_scenario.core.manifest import Manifest, ManifestRecord
from frappe_scenario.core.onboarding import DOCTYPE, NEEDS_SCENARIO, transition_onboarding
from frappe_scenario.core.preflight import preflight_report
from frappe_scenario.core.setup_wizard import build_proposal, validate_choices

PROVIDER = "frappe_scenario.bootstrap"
CAPABILITY = "erpnext.bootstrap"
AUTO_CREATED_DOCTYPES = ("Account", "Warehouse", "Cost Center", "Department")


def execute_approved_bootstrap(*, expected_version: int) -> dict[str, Any]:
	"""Apply the approved setup plan once and move onboarding to Needs Scenario."""
	doc = frappe.get_single(DOCTYPE)
	if int(doc.state_version or 0) != int(expected_version):
		frappe.throw(
			_("Onboarding changed in another session. Refresh and try again."),
			frappe.TimestampMismatchError,
		)
	if doc.bootstrap_completed:
		return _result(doc, changed=False)
	if not doc.setup_approved:
		frappe.throw(_("Approve the setup preview before initializing ERPNext."))

	choices = validate_choices(_decode(doc.setup_choices))
	report = preflight_report()
	proposal = build_proposal(choices, report)
	approved_proposal = _decode(doc.preview)
	if approved_proposal.get("mutations") != proposal.get("mutations"):
		frappe.throw(
			_(
				"Site configuration changed after approval. Refresh, review the new preview, "
				"and approve it again."
			),
			frappe.TimestampMismatchError,
		)
	_validate_execution(choices, report, proposal)

	manifest = _load_manifest(doc.bootstrap_manifest)
	frappe.db.savepoint("frappe_scenario_bootstrap")
	try:
		settings_before = _settings_snapshot(choices)
		_install_master_fixtures_if_needed(choices, report)
		company = _ensure_company(choices, report, manifest)
		fiscal_year = _ensure_fiscal_year(choices, manifest)
		warehouse = _ensure_warehouse(choices, company, manifest)
		_ensure_cost_center(choices, company, manifest)
		_record_planned_setting_changes(
			settings_before,
			choices,
			company,
			fiscal_year,
			warehouse,
			manifest,
		)
		_align_settings(choices, company, fiscal_year, warehouse, manifest)
		_mark_setup_complete(manifest)
		final_report = preflight_report()
		updated = transition_onboarding(
			NEEDS_SCENARIO,
			expected_version=expected_version,
			updates={
				"bootstrap_completed": 1,
				"bootstrap_completed_on": now_datetime(),
				"bootstrap_manifest": _manifest_payload(manifest),
				"last_preflight": final_report,
				"progress": {
					"completed_steps": ["choices", "preview", "setup_approval", "erpnext_bootstrap"],
					"current_state": NEEDS_SCENARIO,
				},
				"errors": None,
			},
		)
	except Exception:
		frappe.db.rollback(save_point="frappe_scenario_bootstrap")
		raise
	return _result(updated, changed=True)


def _validate_execution(
	choices: dict[str, Any],
	report: dict[str, Any],
	proposal: dict[str, Any],
) -> None:
	if not report.get("erpnext", {}).get("installed"):
		frappe.throw(_("ERPNext must be installed before setup can run."))
	if proposal["blockers"]:
		frappe.throw(
			_("Setup cannot run while preflight has blocking findings: {0}").format(
				"; ".join(item["message"] for item in proposal["blockers"])
			),
			frappe.ValidationError,
		)

	strategy = choices["company_strategy"]
	companies = {row["name"]: row for row in report.get("companies") or []}
	existing = companies.get(choices["company_name"])
	if strategy == "require_existing" and proposal["mutations"]:
		frappe.throw(
			_(
				"require_existing refuses all setup mutations; align the site first or choose another strategy."
			),
			frappe.ValidationError,
		)
	if strategy == "isolated_company" and existing:
		frappe.throw(_("isolated_company requires an unused company name."), frappe.ValidationError)
	if strategy in {"require_existing", "reuse_company"} and not existing:
		frappe.throw(_("The selected strategy requires an existing company."), frappe.ValidationError)

	existing_data = int((report.get("existing_business_data") or {}).get("total") or 0)
	if strategy == "reuse_company" and existing_data:
		default_company = (report.get("global_defaults") or {}).get("company")
		if default_company and default_company != choices["company_name"]:
			frappe.throw(
				_(
					"Refusing ambiguous reuse: the selected company is not the site's default "
					"and business data already exists."
				),
				frappe.ValidationError,
			)
		if bool(existing.get("enable_perpetual_inventory")) != choices["perpetual_inventory"]:
			frappe.throw(
				_(
					"Refusing to change perpetual inventory on an existing company that already "
					"has business data."
				),
				frappe.ValidationError,
			)
		stock = report.get("stock") or {}
		if stock.get("valuation_method") not in (None, choices["valuation_method"]):
			frappe.throw(
				_("Refusing to change stock valuation while existing business data is present."),
				frappe.ValidationError,
			)


def _install_master_fixtures_if_needed(choices: dict[str, Any], report: dict[str, Any]) -> None:
	if report.get("setup", {}).get("masters_present"):
		return
	if frappe.db.exists("Warehouse Type", "Transit") and frappe.db.exists("UOM", "Nos"):
		return
	from erpnext.setup.setup_wizard.operations.install_fixtures import install

	install(choices["country"])


def _ensure_company(
	choices: dict[str, Any],
	report: dict[str, Any],
	manifest: Manifest,
) -> str:
	name = choices["company_name"]
	if frappe.db.exists("Company", name):
		company = frappe.get_doc("Company", name)
		if choices["company_strategy"] != "require_existing":
			_set_fields(
				company,
				{"enable_perpetual_inventory": int(choices["perpetual_inventory"])},
				manifest,
			)
		return name

	if choices["company_strategy"] in {"require_existing", "reuse_company"}:
		frappe.throw(_("The selected company no longer exists."), frappe.ValidationError)

	before = _company_children(name)
	chart = choices["chart_template"]
	if choices["account_numbering"] == "With Numbers" and chart == "Standard":
		chart = "Standard with Numbers"
	company = frappe.get_doc(
		{
			"doctype": "Company",
			"company_name": name,
			"abbr": choices["company_abbr"],
			"default_currency": choices["currency"],
			"country": choices["country"],
			"create_chart_of_accounts_based_on": "Standard Template",
			"chart_of_accounts": chart,
			"enable_perpetual_inventory": int(choices["perpetual_inventory"]),
		}
	)
	company.insert(ignore_permissions=True)
	_record_created(manifest, company)
	_record_new_company_children(manifest, name, before)
	return company.name


def _ensure_fiscal_year(choices: dict[str, Any], manifest: Manifest) -> str:
	start = getdate(choices["fiscal_year_start"])
	end = getdate(add_days(add_years(start, 1), -1))
	existing = frappe.db.get_value(
		"Fiscal Year",
		{"year_start_date": start, "year_end_date": end},
		"name",
	)
	if existing:
		_set_fields(frappe.get_doc("Fiscal Year", existing), {"disabled": 0}, manifest)
		return existing
	year = str(start.year) if start.year == end.year else f"{start.year}-{end.year}"
	if frappe.db.exists("Fiscal Year", year):
		year = f"{year} Scenario"
	doc = frappe.get_doc(
		{
			"doctype": "Fiscal Year",
			"year": year,
			"year_start_date": start,
			"year_end_date": end,
		}
	)
	doc.insert(ignore_permissions=True)
	_record_created(manifest, doc)
	return doc.name


def _ensure_warehouse(choices: dict[str, Any], company: str, manifest: Manifest) -> str:
	existing = frappe.db.get_value(
		"Warehouse",
		{"warehouse_name": choices["warehouse_name"], "company": company, "disabled": 0},
		"name",
	)
	if existing:
		return existing
	parent = frappe.db.get_value(
		"Warehouse", {"company": company, "is_group": 1, "parent_warehouse": ""}, "name"
	)
	doc = frappe.get_doc(
		{
			"doctype": "Warehouse",
			"warehouse_name": choices["warehouse_name"],
			"company": company,
			"parent_warehouse": parent,
			"is_group": 0,
		}
	)
	doc.insert(ignore_permissions=True)
	_record_created(manifest, doc)
	return doc.name


def _ensure_cost_center(choices: dict[str, Any], company: str, manifest: Manifest) -> str:
	existing = frappe.db.get_value(
		"Cost Center",
		{"cost_center_name": choices["cost_center_name"], "company": company, "disabled": 0},
		"name",
	)
	if existing:
		return existing
	parent = frappe.db.get_value(
		"Cost Center", {"company": company, "is_group": 1, "parent_cost_center": ""}, "name"
	)
	doc = frappe.get_doc(
		{
			"doctype": "Cost Center",
			"cost_center_name": choices["cost_center_name"],
			"company": company,
			"parent_cost_center": parent,
			"is_group": 0,
		}
	)
	doc.insert(ignore_permissions=True)
	_record_created(manifest, doc)
	return doc.name


def _align_settings(
	choices: dict[str, Any],
	company: str,
	fiscal_year: str,
	warehouse: str,
	manifest: Manifest,
) -> None:
	_set_fields(
		frappe.get_single("Global Defaults"),
		{
			"default_company": company,
			"country": choices["country"],
			"default_currency": choices["currency"],
			"current_fiscal_year": fiscal_year,
		},
		manifest,
	)
	_set_fields(
		frappe.get_single("System Settings"),
		{"language": choices["language"], "time_zone": choices["timezone"]},
		manifest,
	)
	_set_fields(
		frappe.get_single("Stock Settings"),
		{"valuation_method": choices["valuation_method"], "default_warehouse": warehouse},
		manifest,
	)
	if frappe.db.exists("Currency", choices["currency"]):
		_set_fields(frappe.get_doc("Currency", choices["currency"]), {"enabled": 1}, manifest)


def _settings_snapshot(choices: dict[str, Any]) -> dict[str, tuple[Any, dict[str, Any]]]:
	fields = {
		"Global Defaults": ("default_company", "country", "default_currency", "current_fiscal_year"),
		"System Settings": ("language", "time_zone"),
		"Stock Settings": ("valuation_method", "default_warehouse"),
	}
	snapshot = {}
	for doctype, fieldnames in fields.items():
		doc = frappe.get_single(doctype)
		snapshot[doctype] = (doc, {field: doc.get(field) for field in fieldnames})
	if frappe.db.exists("Currency", choices["currency"]):
		doc = frappe.get_doc("Currency", choices["currency"])
		snapshot[f"Currency/{doc.name}"] = (doc, {"enabled": doc.enabled})
	return snapshot


def _record_planned_setting_changes(
	snapshot: dict[str, tuple[Any, dict[str, Any]]],
	choices: dict[str, Any],
	company: str,
	fiscal_year: str,
	warehouse: str,
	manifest: Manifest,
) -> None:
	targets = {
		"Global Defaults": {
			"default_company": company,
			"country": choices["country"],
			"default_currency": choices["currency"],
			"current_fiscal_year": fiscal_year,
		},
		"System Settings": {"language": choices["language"], "time_zone": choices["timezone"]},
		"Stock Settings": {
			"valuation_method": choices["valuation_method"],
			"default_warehouse": warehouse,
		},
		f"Currency/{choices['currency']}": {"enabled": 1},
	}
	for key, (doc, original) in snapshot.items():
		changed = {
			field: value
			for field, value in original.items()
			if field in targets.get(key, {}) and value != targets[key][field]
		}
		if changed:
			_record_modified(manifest, doc, changed)


def _mark_setup_complete(manifest: Manifest) -> None:
	from frappe.desk.page.setup_wizard.setup_wizard import enable_setup_wizard_complete

	for app_name in ("frappe", "erpnext"):
		name = frappe.db.get_value("Installed Application", {"app_name": app_name}, "name")
		if not name:
			continue
		doc = frappe.get_doc("Installed Application", name)
		if not doc.is_setup_complete:
			_record_modified(manifest, doc, {"is_setup_complete": doc.is_setup_complete})
			enable_setup_wizard_complete(app_name)
	frappe.clear_cache()


def _set_fields(doc: Any, values: dict[str, Any], manifest: Manifest) -> None:
	changed = {field: doc.get(field) for field, value in values.items() if doc.get(field) != value}
	if not changed:
		return
	_record_modified(manifest, doc, changed)
	doc.update(values)
	doc.save(ignore_permissions=True)


def _record_created(manifest: Manifest, doc: Any) -> None:
	manifest.append(
		ManifestRecord(
			doctype=doc.doctype,
			name=doc.name,
			provider=PROVIDER,
			capability=CAPABILITY,
			operation="created",
			docstatus=int(doc.docstatus or 0),
		)
	)


def _record_modified(manifest: Manifest, doc: Any, original: dict[str, Any]) -> None:
	manifest.append(
		ManifestRecord(
			doctype=doc.doctype,
			name=doc.name,
			provider=PROVIDER,
			capability=CAPABILITY,
			operation="modified",
			original_values=original,
		)
	)


def _company_children(company: str) -> dict[str, set[str]]:
	return {
		doctype: set(frappe.get_all(doctype, filters={"company": company}, pluck="name"))
		for doctype in AUTO_CREATED_DOCTYPES
	}


def _record_new_company_children(
	manifest: Manifest,
	company: str,
	before: dict[str, set[str]],
) -> None:
	for doctype in AUTO_CREATED_DOCTYPES:
		after = set(frappe.get_all(doctype, filters={"company": company}, pluck="name"))
		for name in sorted(after - before[doctype]):
			_record_created(manifest, frappe.get_doc(doctype, name))


def _load_manifest(value: Any) -> Manifest:
	payload = _decode(value)
	records = payload.get("records") if isinstance(payload, dict) else []
	return Manifest(ManifestRecord.from_dict(record) for record in records or [])


def _manifest_payload(manifest: Manifest) -> dict[str, Any]:
	return {
		"version": "1.0",
		"records": [record.as_dict() for record in manifest],
		"summary": {
			"created": len(manifest.created()),
			"modified": len(manifest.modified()),
			"by_doctype": manifest.counts_by_doctype(),
		},
	}


def _decode(value: Any) -> dict[str, Any]:
	if isinstance(value, dict):
		return value
	if not value:
		return {}
	try:
		return json.loads(value)
	except (TypeError, ValueError):
		return {}


def _result(doc: Any, *, changed: bool) -> dict[str, Any]:
	payload = doc.as_dict()
	for field in ("setup_choices", "preview", "progress", "errors", "last_preflight", "bootstrap_manifest"):
		payload[field] = _decode(payload.get(field))
	return {
		"onboarding": payload,
		"bootstrap": payload.get("bootstrap_manifest") or {},
		"changed": changed,
		"generates_data": False,
	}
