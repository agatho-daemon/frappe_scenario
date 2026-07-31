# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Shared onboarding choices, preview, and approval services."""

from __future__ import annotations

import datetime
import json
import re
from copy import deepcopy
from typing import Any

import frappe
from frappe import _
from frappe.utils import now_datetime

from frappe_scenario.archetypes import describe_archetypes
from frappe_scenario.core.lifecycle import (
	OPERATIONAL_DEPTHS,
	PRODUCT_INTENTS,
	derive_lifecycle_counts,
)
from frappe_scenario.core.onboarding import DOCTYPE, json_fields, transition_onboarding
from frappe_scenario.core.preflight import BLOCKING, preflight_report
from frappe_scenario.core.realism_preview import representative_preview
from frappe_scenario.core.scale import get_scale_profile
from frappe_scenario.locales import describe_country_packs

INTENTS = PRODUCT_INTENTS
DEPTHS = OPERATIONAL_DEPTHS
COMPANY_STRATEGIES = (
	"initialize_if_needed",
	"require_existing",
	"isolated_company",
	"reuse_company",
)
ACCOUNT_NUMBERING = ("Without Numbers", "With Numbers")
VALUATION_METHODS = ("FIFO", "Moving Average")

ABBR = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")
CURRENCY = re.compile(r"^[A-Z]{3}$")


def wizard_context() -> dict[str, Any]:
	"""Return everything either client needs to render or resume the wizard."""
	doc = frappe.get_single(DOCTYPE)
	report = preflight_report()
	saved = _decode(doc.setup_choices) or {}
	choices = default_choices(report)
	choices.update(saved)
	proposal = build_proposal(choices, report)
	stored_preview = _decode(doc.preview)
	return {
		"onboarding": _serialize_onboarding(doc),
		"preflight": report,
		"catalog": choice_catalog(),
		"choices": choices,
		"proposal": proposal,
		"preview_is_saved": stored_preview == proposal,
	}


def choice_catalog() -> dict[str, Any]:
	return {
		"intents": list(INTENTS),
		"depths": list(DEPTHS),
		"company_strategies": list(COMPANY_STRATEGIES),
		"account_numbering": list(ACCOUNT_NUMBERING),
		"valuation_methods": list(VALUATION_METHODS),
		"archetypes": describe_archetypes(),
		"country_packs": describe_country_packs(),
		"guidance": {
			"initialize_if_needed": "Recommended: fill only missing ERPNext foundations.",
			"require_existing": "Refuse to continue unless ERPNext is already configured.",
			"isolated_company": "Create a separate company and leave existing companies untouched.",
			"reuse_company": "Use an existing company; cleanup guarantees will be limited.",
		},
	}


def default_choices(report: dict[str, Any]) -> dict[str, Any]:
	defaults = report.get("global_defaults") or {}
	companies = report.get("companies") or []
	company = _default_company(companies, defaults.get("company"))
	now = datetime.date.today()
	return {
		"intent": "Quick Demo",
		"archetype": "hvac_distribution",
		"depth": "Everyday Business",
		"company_strategy": "initialize_if_needed",
		"country": defaults.get("country") or "Kuwait",
		"language": defaults.get("language") or "en",
		"timezone": defaults.get("timezone") or "Asia/Kuwait",
		"currency": defaults.get("currency") or "KWD",
		"company_name": company.get("name") or "Example Trading Company",
		"company_abbr": company.get("abbr") or "ETC",
		"chart_template": "Standard",
		"account_numbering": "Without Numbers",
		"fiscal_year_start": f"{now.year}-01-01",
		"perpetual_inventory": True,
		"valuation_method": "Moving Average",
		"warehouse_name": "Stores",
		"cost_center_name": "Main",
		"scale": "smoke",
		"history_months": get_scale_profile("smoke")["history_months"],
		"preview_variation": 0,
	}


def save_choices(
	choices: dict[str, Any],
	*,
	expected_version: int,
) -> dict[str, Any]:
	"""Validate choices, persist them, and return a non-mutating proposal."""
	report = preflight_report()
	resolved = validate_choices(choices)
	proposal = build_proposal(resolved, report)
	doc = frappe.get_single(DOCTYPE)
	updated = transition_onboarding(
		doc.status,
		expected_version=expected_version,
		updates={
			"intent": resolved["intent"],
			"archetype": resolved["archetype"],
			"depth": resolved["depth"],
			"scale": resolved["scale"],
			"setup_choices": resolved,
			"preview": proposal,
			"progress": {
				"completed_steps": ["choices", "preview"],
				"current_state": doc.status,
			},
			"last_preflight": report,
			"setup_approved": 0,
			"setup_approved_by": None,
			"setup_approved_on": None,
		},
	)
	return {
		"onboarding": _serialize_onboarding(updated),
		"choices": resolved,
		"proposal": proposal,
		"preview_is_saved": True,
	}


def approve_setup(*, expected_version: int) -> dict[str, Any]:
	"""Record explicit approval; execute no setup and generate no records."""
	doc = frappe.get_single(DOCTYPE)
	proposal = _decode(doc.preview)
	if not proposal:
		frappe.throw(_("Preview the onboarding choices before approving setup."))
	if not proposal.get("approvable"):
		frappe.throw(
			_("The setup proposal has blocking prerequisites and cannot be approved."),
			frappe.ValidationError,
		)

	updated = transition_onboarding(
		doc.status,
		expected_version=expected_version,
		updates={
			"setup_approved": 1,
			"setup_approved_by": frappe.session.user,
			"setup_approved_on": now_datetime(),
			"progress": {
				"completed_steps": ["choices", "preview", "setup_approval"],
				"current_state": doc.status,
			},
		},
	)
	return {"onboarding": _serialize_onboarding(updated), "proposal": proposal}


def validate_choices(choices: dict[str, Any]) -> dict[str, Any]:
	if not isinstance(choices, dict):
		frappe.throw(_("Onboarding choices must be a JSON object."), frappe.ValidationError)
	resolved = deepcopy(choices)
	if not resolved.get("depth") and resolved.get("complexity"):
		resolved["depth"] = resolved["complexity"]
	resolved.pop("complexity", None)
	_required(resolved)
	_choice(resolved, "intent", INTENTS)
	_choice(resolved, "depth", DEPTHS)
	_choice(resolved, "company_strategy", COMPANY_STRATEGIES)
	_choice(resolved, "account_numbering", ACCOUNT_NUMBERING)
	_choice(resolved, "valuation_method", VALUATION_METHODS)

	available_archetypes = {entry["id"] for entry in describe_archetypes()}
	if resolved["archetype"] not in available_archetypes:
		frappe.throw(_("Unknown business archetype."), frappe.ValidationError)
	if not ABBR.fullmatch(str(resolved["company_abbr"]).upper()):
		frappe.throw(
			_("Company abbreviation must be 2-10 uppercase letters or digits."),
			frappe.ValidationError,
		)
	if not CURRENCY.fullmatch(str(resolved["currency"]).upper()):
		frappe.throw(_("Currency must be a three-letter code."), frappe.ValidationError)

	try:
		datetime.date.fromisoformat(str(resolved["fiscal_year_start"]))
	except (TypeError, ValueError):
		frappe.throw(_("Fiscal year start must be an ISO date."), frappe.ValidationError)

	resolved["company_abbr"] = str(resolved["company_abbr"]).upper()
	resolved["currency"] = str(resolved["currency"]).upper()
	try:
		resolved["history_months"] = int(resolved["history_months"])
	except (TypeError, ValueError):
		frappe.throw(_("History must be a whole number of months."), frappe.ValidationError)
	if not 1 <= resolved["history_months"] <= 60:
		frappe.throw(_("History must be between 1 and 60 months."), frappe.ValidationError)
	try:
		resolved["preview_variation"] = int(resolved.get("preview_variation") or 0)
	except (TypeError, ValueError):
		frappe.throw(_("Preview variation must be a whole number."), frappe.ValidationError)
	if not 0 <= resolved["preview_variation"] <= 1000:
		frappe.throw(_("Preview variation must be between 0 and 1000."), frappe.ValidationError)
	if isinstance(resolved["perpetual_inventory"], str):
		resolved["perpetual_inventory"] = resolved["perpetual_inventory"].strip().lower() in {
			"1",
			"true",
			"yes",
		}
	else:
		resolved["perpetual_inventory"] = bool(resolved["perpetual_inventory"])
	get_scale_profile(resolved["scale"])
	return resolved


def build_proposal(choices: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
	choices = validate_choices(choices)
	mutations: list[dict[str, Any]] = []
	defaults = report.get("global_defaults") or {}
	if not report.get("setup", {}).get("complete"):
		mutations.append(
			{
				"action": "initialize",
				"target": "ERPNext foundations",
				"field": "setup",
				"current": "incomplete",
				"proposed": "complete missing initial settings",
				"reason": "ERPNext setup is incomplete.",
			}
		)
	_add_change(
		mutations,
		"Global Defaults",
		"default_company",
		defaults.get("company"),
		choices["company_name"],
	)
	_add_change(mutations, "Global Defaults", "country", defaults.get("country"), choices["country"])
	_add_change(
		mutations, "Global Defaults", "default_currency", defaults.get("currency"), choices["currency"]
	)
	_add_change(mutations, "System Settings", "language", defaults.get("language"), choices["language"])
	_add_change(mutations, "System Settings", "time_zone", defaults.get("timezone"), choices["timezone"])

	companies = {company["name"]: company for company in report.get("companies") or []}
	company = companies.get(choices["company_name"])
	if not company:
		mutations.append(
			{
				"action": "create",
				"target": "Company",
				"field": choices["company_name"],
				"current": None,
				"proposed": {
					"abbr": choices["company_abbr"],
					"country": choices["country"],
					"currency": choices["currency"],
				},
				"reason": "The selected company does not exist.",
			}
		)
	else:
		_add_change(
			mutations,
			f"Company: {choices['company_name']}",
			"enable_perpetual_inventory",
			bool(company.get("enable_perpetual_inventory")),
			choices["perpetual_inventory"],
		)

	accounts = (report.get("chart_of_accounts") or {}).get("by_company", {}).get(choices["company_name"], {})
	blockers_numbering = None
	if not accounts.get("total"):
		mutations.append(
			{
				"action": "create",
				"target": "Chart of Accounts",
				"field": choices["company_name"],
				"current": None,
				"proposed": {
					"template": choices["chart_template"],
					"numbering": choices["account_numbering"],
				},
				"reason": "The selected company has no Chart of Accounts.",
			}
		)
	elif (choices["account_numbering"] == "With Numbers" and accounts.get("unnumbered")) or (
		choices["account_numbering"] == "Without Numbers" and accounts.get("numbered")
	):
		blockers_numbering = {
			"key": "chart_of_accounts.numbering",
			"classification": BLOCKING,
			"message": (
				"The existing Chart of Accounts uses a different numbering mode. "
				"Bootstrap will not renumber an established chart."
			),
		}

	fiscal_year_exists = any(
		str(year.get("year_start_date")) == choices["fiscal_year_start"] and not year.get("disabled")
		for year in report.get("fiscal_years") or []
	)
	if not fiscal_year_exists:
		mutations.append(
			{
				"action": "create",
				"target": "Fiscal Year",
				"field": choices["fiscal_year_start"],
				"current": None,
				"proposed": {"year_start_date": choices["fiscal_year_start"]},
				"reason": "No active fiscal year starts on the selected date.",
			}
		)

	organization = report.get("organization") or {}
	warehouse_exists = any(
		row.get("warehouse_name") == choices["warehouse_name"]
		and row.get("company") == choices["company_name"]
		for row in organization.get("warehouses") or []
	)
	if not warehouse_exists:
		mutations.append(
			{
				"action": "create",
				"target": "Warehouse",
				"field": choices["warehouse_name"],
				"current": None,
				"proposed": {"company": choices["company_name"]},
				"reason": "The selected company has no matching warehouse.",
			}
		)
	cost_center_exists = any(
		row.get("cost_center_name") == choices["cost_center_name"]
		and row.get("company") == choices["company_name"]
		for row in organization.get("cost_centers") or []
	)
	if not cost_center_exists:
		mutations.append(
			{
				"action": "create",
				"target": "Cost Center",
				"field": choices["cost_center_name"],
				"current": None,
				"proposed": {"company": choices["company_name"]},
				"reason": "The selected company has no matching cost center.",
			}
		)

	stock = report.get("stock") or {}
	_add_change(
		mutations,
		"Stock Settings",
		"valuation_method",
		stock.get("valuation_method"),
		choices["valuation_method"],
	)
	_add_change(
		mutations,
		"Stock Settings",
		"default_warehouse",
		stock.get("default_warehouse"),
		choices["warehouse_name"],
	)

	blockers = [
		finding for finding in report.get("findings", []) if finding.get("classification") == BLOCKING
	]
	if accounts.get("total") and blockers_numbering:
		blockers.append(blockers_numbering)
	if choices["company_strategy"] in {"require_existing", "reuse_company"} and not company:
		blockers.append(
			{
				"key": "company_strategy",
				"classification": BLOCKING,
				"message": (
					f"Company strategy {choices['company_strategy']!r} requires "
					f"existing company {choices['company_name']!r}."
				),
			}
		)
	if choices["company_strategy"] == "require_existing" and not report.get("setup", {}).get("complete"):
		blockers.append(
			{
				"key": "erpnext.setup",
				"classification": BLOCKING,
				"message": "require_existing cannot continue until ERPNext setup is complete.",
			}
		)
	if choices["company_strategy"] == "require_existing" and mutations:
		blockers.append(
			{
				"key": "company_strategy",
				"classification": BLOCKING,
				"message": "require_existing refuses setup mutations; align the site first.",
			}
		)
	if choices["company_strategy"] == "isolated_company" and company:
		blockers.append(
			{
				"key": "company_strategy",
				"classification": BLOCKING,
				"message": "isolated_company requires a new, unused company name.",
			}
		)
	existing_data = int((report.get("existing_business_data") or {}).get("total") or 0)
	if choices["company_strategy"] == "reuse_company" and company and existing_data:
		if defaults.get("company") and defaults.get("company") != choices["company_name"]:
			blockers.append(
				{
					"key": "company_strategy",
					"classification": BLOCKING,
					"message": (
						"Refusing ambiguous reuse because the selected company is not the "
						"site default and business data already exists."
					),
				}
			)
		if bool(company.get("enable_perpetual_inventory")) != choices["perpetual_inventory"]:
			blockers.append(
				{
					"key": "company.perpetual_inventory",
					"classification": BLOCKING,
					"message": (
						"Perpetual inventory cannot be changed while the reused company "
						"has existing business data."
					),
				}
			)
		stock = report.get("stock") or {}
		if stock.get("valuation_method") not in (None, choices["valuation_method"]):
			blockers.append(
				{
					"key": "stock.valuation_method",
					"classification": BLOCKING,
					"message": ("Stock valuation cannot be changed while existing business data is present."),
				}
			)
	return {
		"choices": choices,
		"mutations": mutations,
		"mutation_count": len(mutations),
		"record_estimate": estimate_records(choices),
		"representative_samples": representative_preview(choices),
		"blockers": blockers,
		"warnings": _proposal_warnings(choices, report),
		"approvable": not blockers,
		"executes_setup": False,
		"generates_data": False,
	}


def estimate_records(choices: dict[str, Any]) -> dict[str, Any]:
	profile = get_scale_profile(choices["scale"])
	months = choices["history_months"]
	parties = profile["parties"]
	items = profile["catalog"]["item_count"]
	sales = profile["operations"]["sales_orders_per_month"] * months
	purchases = profile["operations"]["purchase_orders_per_month"] * months
	lifecycle = derive_lifecycle_counts(
		sales_activities=sales,
		purchase_orders=purchases,
		depth=choices["depth"],
		cash_sales_ratio=0.15,
	)
	breakdown = {
		"foundations": 80,
		"parties_contacts_addresses": sum(parties.values()) * 3,
		"catalog": items * 2,
		"selling_lifecycle": sum(
			lifecycle[key]
			for key in ("sales_orders", "delivery_notes", "sales_invoices", "customer_payments")
		),
		"buying_lifecycle": sum(
			lifecycle[key]
			for key in (
				"purchase_orders",
				"purchase_receipts",
				"purchase_invoices",
				"supplier_payments",
			)
		),
		"accounting_and_stock": lifecycle["delivery_notes"]
		+ lifecycle["purchase_receipts"]
		+ lifecycle["customer_payments"]
		+ lifecycle["supplier_payments"],
	}
	approximate = sum(breakdown.values())
	target = profile["record_target"]
	database_rows = round(approximate + (sales + purchases) * 7.5)
	storage_typical = round(database_rows * 2.75 / 1024, 1)
	return {
		"approximate": approximate,
		"minimum": target["minimum"],
		"maximum": target["maximum"],
		"target": target["typical"],
		"history_months": months,
		"breakdown": breakdown,
		"lifecycle": lifecycle,
		"database_rows": database_rows,
		"storage_mb": {
			"minimum": round(storage_typical * 0.7, 1),
			"typical": storage_typical,
			"maximum": round(storage_typical * 1.5, 1),
		},
		"runtime_minutes": {
			"minimum": max(1, approximate // 900),
			"maximum": max(2, -(-approximate // 180)),
		},
		"confirmation_required": bool(profile.get("confirmation_required")),
	}


def _proposal_warnings(choices: dict[str, Any], report: dict[str, Any]) -> list[str]:
	warnings = []
	if choices["company_strategy"] == "reuse_company":
		warnings.append("Reusing a company limits cleanup guarantees for shared records and settings.")
	if (report.get("existing_business_data") or {}).get("total"):
		warnings.append("The site already contains business data; existing records will be preserved.")
	if get_scale_profile(choices["scale"]).get("confirmation_required"):
		warnings.append(
			"Large generation may create tens of thousands of records. Use a disposable site and "
			"keep a long worker running."
		)
	return warnings


def _add_change(
	mutations: list[dict[str, Any]],
	target: str,
	field: str,
	current: Any,
	proposed: Any,
) -> None:
	if current == proposed:
		return
	mutations.append(
		{
			"action": "set",
			"target": target,
			"field": field,
			"current": current,
			"proposed": proposed,
			"reason": "Current value differs from the selected onboarding choice.",
		}
	)


def _required(choices: dict[str, Any]) -> None:
	required = {
		"intent",
		"archetype",
		"depth",
		"company_strategy",
		"country",
		"language",
		"timezone",
		"currency",
		"company_name",
		"company_abbr",
		"chart_template",
		"account_numbering",
		"fiscal_year_start",
		"perpetual_inventory",
		"valuation_method",
		"warehouse_name",
		"cost_center_name",
		"scale",
		"history_months",
	}
	missing = sorted(key for key in required if choices.get(key) in (None, ""))
	if missing:
		frappe.throw(
			_("Required onboarding choices are missing: {0}.").format(", ".join(missing)),
			frappe.ValidationError,
		)


def _choice(choices: dict[str, Any], key: str, allowed: tuple[str, ...]) -> None:
	if choices[key] not in allowed:
		frappe.throw(
			_("Invalid {0}. Choose one of: {1}.").format(key, ", ".join(allowed)),
			frappe.ValidationError,
		)


def _default_company(companies: list[dict[str, Any]], preferred: str | None) -> dict[str, Any]:
	for company in companies:
		if company.get("name") == preferred:
			return company
	return companies[0] if companies else {}


def _decode(value: Any) -> Any:
	if not value:
		return {}
	if isinstance(value, dict):
		return value
	try:
		return json.loads(value)
	except (TypeError, ValueError):
		return {}


def _serialize_onboarding(doc: Any) -> dict[str, Any]:
	payload = doc.as_dict()
	for fieldname in json_fields():
		payload[fieldname] = _decode(payload.get(fieldname))
	return payload
