# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Deterministic preview and generated-dataset quality gates."""

from __future__ import annotations

import json
from typing import Any

import frappe

from frappe_scenario.providers.support.realism import address_findings, name_findings

DIMENSIONS = ("naming", "regional_consistency", "linkage", "accounting", "continuity")
READY = "Ready"
REVIEW = "Needs Review"
BLOCKED = "Blocked"


def assess_preview(samples: dict[str, Any]) -> dict[str, Any]:
	"""Score insertion-free samples and decide whether generation may proceed."""
	findings: list[dict[str, Any]] = []
	expected_country = samples.get("country")
	parties = samples.get("parties") or []
	products = samples.get("products") or []
	stories = samples.get("transaction_stories") or []

	for party in parties:
		for finding in name_findings(party.get("name") or ""):
			findings.append(_finding("naming", finding.severity, finding.message, finding.field))
		for finding in address_findings(
			party.get("address") or {},
			expected_country=expected_country,
		):
			findings.append(
				_finding("regional_consistency", finding.severity, finding.message, finding.field)
			)
		if not str(party.get("email") or "").lower().endswith(".example"):
			findings.append(
				_finding(
					"regional_consistency",
					"error",
					"Generated e-mail is not under a reserved .example domain.",
					"email",
				)
			)
	for product in products:
		for finding in name_findings(product.get("name") or "", allow_legal_form=False):
			findings.append(_finding("naming", finding.severity, finding.message, finding.field))
		if float(product.get("cost") or 0) <= 0 or float(product.get("selling_price") or 0) <= float(
			product.get("cost") or 0
		):
			findings.append(
				_finding(
					"accounting",
					"error",
					"Representative selling price must be positive and above cost.",
					"selling_price",
				)
			)

	party_names = {entry.get("name") for entry in parties}
	product_names = {entry.get("name") for entry in products}
	expected_lifecycle = ["Sales Order", "Delivery Note", "Sales Invoice", "Payment Entry"]
	for story in stories:
		if story.get("customer") not in party_names or story.get("item") not in product_names:
			findings.append(
				_finding("linkage", "error", "Transaction story references an unknown sample record.")
			)
		if story.get("lifecycle") != expected_lifecycle:
			findings.append(
				_finding("continuity", "warning", "Transaction story does not show the full lifecycle.")
			)
	if not stories:
		findings.append(_finding("continuity", "error", "Preview contains no transaction story."))

	return _report(findings)


def assess_generated(
	*,
	specification: dict[str, Any],
	capabilities: dict[str, Any],
	validation: dict[str, Any],
	regional_records: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
	"""Score generated records from stable capability metadata and validator evidence."""
	findings: list[dict[str, Any]] = []
	regional_records = regional_records or {}
	for issue in validation.get("issues") or []:
		category = _category_for_rule(issue.get("rule") or "")
		findings.append(
			_finding(
				category,
				issue.get("severity") or "warning",
				issue.get("message") or issue.get("rule") or "Validation finding",
				issue.get("record"),
				rule=issue.get("rule"),
			)
		)

	expected_country = (specification.get("scenario") or {}).get("country")
	for address in regional_records.get("addresses") or []:
		for finding in address_findings(address, expected_country=expected_country):
			findings.append(
				_finding(
					"regional_consistency",
					finding.severity,
					finding.message,
					address.get("name"),
				)
			)
	for contact in regional_records.get("contacts") or []:
		email = str(contact.get("email_id") or "").lower()
		if email and not email.endswith(".example"):
			findings.append(
				_finding(
					"regional_consistency",
					"error",
					"Generated contact e-mail is not under a reserved .example domain.",
					contact.get("name"),
				)
			)

	for capability in (
		"erpnext.parties.customers",
		"erpnext.parties.suppliers",
		"erpnext.parties.leads",
	):
		for entry in capabilities.get(capability) or []:
			name = entry.get("name") if isinstance(entry, dict) else str(entry)
			for finding in name_findings(name or ""):
				findings.append(_finding("naming", finding.severity, finding.message, name))
	for entry in capabilities.get("erpnext.catalog.items") or []:
		for finding in name_findings(
			entry.get("item_name") or entry.get("name") or "", allow_legal_form=False
		):
			findings.append(_finding("naming", finding.severity, finding.message, entry.get("name")))

	sales = capabilities.get("erpnext.selling.sales_invoices") or []
	unlinked_sales = [
		entry
		for entry in sales
		if not entry.get("delivery_note") and entry.get("channel") not in {"cash", "counter"}
	]
	if unlinked_sales:
		findings.append(
			_finding(
				"linkage",
				"error",
				f"{len(unlinked_sales)} sales invoices lack a delivery or counter-sale lifecycle.",
			)
		)
	purchases = capabilities.get("erpnext.buying.purchase_invoices") or []
	unlinked_purchases = [entry for entry in purchases if not entry.get("purchase_receipt")]
	if unlinked_purchases:
		findings.append(
			_finding(
				"linkage",
				"error",
				f"{len(unlinked_purchases)} purchase invoices lack a purchase receipt link.",
			)
		)

	dates = [
		entry.get(key)
		for entries in capabilities.values()
		if isinstance(entries, list)
		for entry in entries
		if isinstance(entry, dict)
		for key in ("posting_date", "order_date")
		if entry.get(key)
	]
	history_months = int((specification.get("scenario") or {}).get("history_months") or 1)
	distinct_months = {str(value)[:7] for value in dates}
	minimum_months = min(history_months, 2)
	if len(distinct_months) < minimum_months:
		findings.append(
			_finding(
				"continuity",
				"warning",
				f"Activity spans {len(distinct_months)} month(s); expected at least {minimum_months}.",
			)
		)

	return _report(findings)


def persist_generated_report(run: Any, report: dict[str, Any]) -> str:
	"""Create or update the auditable quality report belonging to a run."""
	name = frappe.db.get_value("Scenario Quality Report", {"scenario_run": run.name}, "name")
	payload = {
		"scenario_run": run.name,
		"stage": "Generated",
		"status": report["status"],
		"overall_score": report["overall_score"],
		"confirmation_required": report["confirmation_required"],
		"scores": json.dumps(report["scores"], indent="\t"),
		"findings": json.dumps(report["findings"], indent="\t", default=str),
	}
	if name:
		doc = frappe.get_doc("Scenario Quality Report", name)
		doc.update(payload)
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc({"doctype": "Scenario Quality Report", **payload})
		doc.insert(ignore_permissions=True)
	run.db_set("quality_report", doc.name, update_modified=False)
	return doc.name


def _report(findings: list[dict[str, Any]]) -> dict[str, Any]:
	scores = {dimension: 100 for dimension in DIMENSIONS}
	for finding in findings:
		deduction = 35 if finding["severity"] == "error" else 12 if finding["severity"] == "warning" else 0
		category = finding["category"]
		scores[category] = max(0, scores[category] - deduction)
	blocked = any(finding["severity"] == "error" for finding in findings)
	overall = round(sum(scores.values()) / len(scores))
	confirmation_required = not blocked and (
		overall < 90 or any(finding["severity"] == "warning" for finding in findings)
	)
	return {
		"status": BLOCKED if blocked else REVIEW if confirmation_required else READY,
		"passed": not blocked,
		"confirmation_required": confirmation_required,
		"overall_score": overall,
		"scores": scores,
		"findings": findings,
	}


def _finding(
	category: str,
	severity: str,
	message: str,
	field: str | None = None,
	**extra: Any,
) -> dict[str, Any]:
	return {
		"category": category,
		"severity": severity,
		"message": message,
		"field": field,
		**extra,
	}


def _category_for_rule(rule: str) -> str:
	if any(
		token in rule
		for token in ("ledger", "account", "payment", "capital", "valuation", ".gl_", "balanced")
	):
		return "accounting"
	if any(token in rule for token in ("link", "receipt", "delivery")):
		return "linkage"
	if any(token in rule for token in ("date", "season", "overdue", "fiscal")):
		return "continuity"
	if any(token in rule for token in ("locale", "country", "currency", "address")):
		return "regional_consistency"
	return "naming" if "name" in rule else "linkage"
