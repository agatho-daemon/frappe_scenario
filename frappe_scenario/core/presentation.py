# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Curated Presentation Demo compilation and evidence-backed Desk model."""

from __future__ import annotations

import datetime
import hashlib
import html
import json
from typing import Any

import frappe

from frappe_scenario.core.quick_demo import (
	_generate_demo,
	compile_quick_demo_specification,
)

PALETTES = (
	("#0F766E", "#14B8A6", "#ECFDF5"),
	("#1D4ED8", "#60A5FA", "#EFF6FF"),
	("#7C3AED", "#A78BFA", "#F5F3FF"),
	("#B45309", "#F59E0B", "#FFFBEB"),
)

COPY = {
	"en": {
		"tagline": "A connected view of customers, operations, inventory, and finance.",
		"overview": "Business overview",
		"recent": "Recent business activity",
		"tour": "Guided ERPNext tour",
	},
	"ar": {
		"tagline": "عرض مترابط للعملاء والعمليات والمخزون والمالية.",
		"overview": "نظرة عامة على الأعمال",
		"recent": "أحدث الأنشطة التجارية",
		"tour": "جولة إرشادية في ERPNext",
	},
}


def compile_presentation_specification(
	choices: dict[str, Any], *, anchor_date: datetime.date | None = None
) -> dict[str, Any]:
	"""Compile the polished preset through the same deterministic providers."""
	specification = compile_quick_demo_specification(choices, anchor_date=anchor_date)
	specification["title"] = f"{choices['company_name']} — Presentation Demo"
	specification["scenario"]["intent"] = "Presentation Demo"
	specification["operations"].update({"partial_deliveries": 0.05, "returns": 0.04})
	specification["accounting"].update({"overdue_receivables": 0.08})
	specification["presentation"] = {
		"include_logo": True,
		"bilingual": True,
		"guided_tour": True,
		"identity_style": "Modern",
	}
	return specification


def generate_presentation_demo(
	*,
	expected_version: int,
	allow_non_disposable: bool = False,
) -> dict[str, Any]:
	"""Generate only a warning-free Presentation Demo from approved onboarding."""
	return _generate_demo(
		expected_version=expected_version,
		intent="Presentation Demo",
		compiler=compile_presentation_specification,
		progress_step="presentation_demo_generation",
		allow_non_disposable=allow_non_disposable,
		accept_quality_warnings=False,
		require_warning_free=True,
	)


def presentation_home(run_name: str) -> dict[str, Any]:
	"""Build a read-only presentation dashboard from recorded scenario evidence."""
	run = frappe.get_doc("Scenario Run", run_name)
	run.check_permission("read")
	specification = json.loads(run.specification or "{}")
	if (specification.get("scenario") or {}).get("intent") != "Presentation Demo":
		frappe.throw("This run is not a Presentation Demo.", frappe.ValidationError)
	if run.status != "Completed":
		frappe.throw("Presentation is available only for a completed run.", frappe.ValidationError)

	validation = json.loads(run.validation_summary or "{}")
	counts = validation.get("counts") or {}
	quality = None
	if run.quality_report:
		quality = frappe.get_doc("Scenario Quality Report", run.quality_report)
	if (
		counts.get("error")
		or counts.get("warning")
		or not quality
		or quality.status != "Ready"
		or quality.confirmation_required
	):
		frappe.throw(
			"Presentation Demo has unresolved quality findings and cannot be presented.",
			frappe.ValidationError,
		)

	capabilities = json.loads(run.published_capabilities or "{}")
	scenario = specification["scenario"]
	presentation = specification.get("presentation") or {}
	identity = _identity(run.company or run.title, scenario, presentation)
	return {
		"run": {
			"name": run.name,
			"title": run.title,
			"company": run.company,
			"anchor_date": str(run.anchor_date),
			"currency": run.currency,
		},
		"identity": identity,
		"copy": _bilingual_copy(scenario, bool(presentation.get("bilingual", True))),
		"metrics": _metrics(capabilities, run.currency),
		"recent_activity": _recent_activity(run.name),
		"tour": _tour(capabilities) if presentation.get("guided_tour", True) else [],
		"quality": {
			"status": quality.status,
			"overall_score": quality.overall_score,
			"counts": counts,
		},
	}


def export_presentation(run_name: str) -> dict[str, Any]:
	"""Export an approved, secret-free presentation specification and identity."""
	model = presentation_home(run_name)
	run = frappe.get_doc("Scenario Run", run_name)
	return {
		"format": "frappe-scenario-presentation-1",
		"specification": json.loads(run.specification),
		"specification_hash": run.specification_hash,
		"canonical_hash": run.canonical_hash,
		"identity": model["identity"],
		"copy": model["copy"],
	}


def _identity(company: str, scenario: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
	digest = hashlib.blake2b(
		f"{company}|{scenario.get('archetype')}|{scenario.get('seed')}".encode(), digest_size=4
	).digest()
	palette = PALETTES[int.from_bytes(digest, "big") % len(PALETTES)]
	initials = "".join(word[0] for word in company.split() if word)[:3].upper() or "SCN"
	return {
		"company": company,
		"style": options.get("identity_style") or "Modern",
		"palette": {"primary": palette[0], "accent": palette[1], "surface": palette[2]},
		"initials": initials,
		"logo_svg": _logo_svg(initials, palette) if options.get("include_logo", True) else None,
	}


def _logo_svg(initials: str, palette: tuple[str, str, str]) -> str:
	safe = html.escape(initials)
	return (
		f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 160" role="img">'
		f'<rect width="160" height="160" rx="32" fill="{palette[0]}"/>'
		f'<circle cx="124" cy="36" r="24" fill="{palette[1]}" opacity=".9"/>'
		f'<text x="80" y="98" text-anchor="middle" font-family="sans-serif" '
		f'font-size="46" font-weight="700" fill="white">{safe}</text></svg>'
	)


def _bilingual_copy(scenario: dict[str, Any], enabled: bool) -> dict[str, Any]:
	locales = scenario.get("locale") or {}
	primary = str(locales.get("primary") or "en").split("_")[0]
	secondary = str(locales.get("secondary") or "en").split("_")[0]
	primary = primary if primary in COPY else "en"
	secondary = secondary if secondary in COPY else "en"
	return {
		"primary_locale": locales.get("primary") or "en_US",
		"primary": COPY[primary],
		"secondary_locale": locales.get("secondary") if enabled else None,
		"secondary": COPY[secondary] if enabled else None,
	}


def _metrics(capabilities: dict[str, Any], currency: str) -> list[dict[str, Any]]:
	invoices = capabilities.get("erpnext.selling.sales_invoices") or []
	return [
		{
			"key": "customers",
			"label": "Customers",
			"value": len(capabilities.get("erpnext.parties.customers") or []),
			"route": "/app/customer",
		},
		{
			"key": "items",
			"label": "Products and services",
			"value": len(capabilities.get("erpnext.catalog.items") or []),
			"route": "/app/item",
		},
		{"key": "sales", "label": "Sales invoices", "value": len(invoices), "route": "/app/sales-invoice"},
		{
			"key": "revenue",
			"label": "Invoiced revenue",
			"value": round(sum(float(row.get("grand_total") or 0) for row in invoices), 2),
			"currency": currency,
			"route": "/app/query-report/Accounts Receivable",
		},
	]


def _recent_activity(run_name: str) -> list[dict[str, Any]]:
	return [
		{
			"date": str(row.event_date),
			"type": row.event_type,
			"title": row.title,
			"doctype": row.reference_doctype,
			"name": row.reference_name,
			"route": f"/app/{frappe.scrub(row.reference_doctype).replace('_', '-')}/{row.reference_name}",
		}
		for row in frappe.get_all(
			"Scenario Event",
			filters={"scenario_run": run_name},
			fields=["event_date", "event_type", "title", "reference_doctype", "reference_name"],
			order_by="event_date desc, sequence desc",
			limit=8,
		)
	]


def _tour(capabilities: dict[str, Any]) -> list[dict[str, Any]]:
	steps = (
		(
			"Customers",
			"Meet the parties behind the sales story.",
			"erpnext.parties.customers",
			"/app/customer",
		),
		(
			"Selling",
			"Follow orders through delivery, invoicing, and payment.",
			"erpnext.selling.sales_invoices",
			"/app/sales-invoice",
		),
		(
			"Stock",
			"Inspect products, warehouses, and current quantities.",
			"erpnext.catalog.items",
			"/app/query-report/Stock Balance",
		),
		(
			"Accounting",
			"Review receivables and the resulting books.",
			"erpnext.accounts.customer_payments",
			"/app/query-report/Accounts Receivable",
		),
	)
	return [
		{
			"sequence": index,
			"title": title,
			"description": description,
			"route": route,
			"evidence_count": len(capabilities.get(capability) or []),
		}
		for index, (title, description, capability, route) in enumerate(steps, start=1)
		if capabilities.get(capability)
	]
