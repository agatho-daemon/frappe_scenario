# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Versioned built-in ERPNext learning paths.

Definitions are data, while verification is a closed server-side vocabulary.
No lesson can supply Python, JavaScript, or an eval expression.
"""

from __future__ import annotations

from typing import Any

CATALOG_VERSION = "1.2"

STEP_TYPES = {
	"explain",
	"open_document",
	"open_report",
	"highlight_field",
	"inspect_value",
	"enter_value",
	"save",
	"submit",
	"follow_link",
	"verify_document",
	"verify_report",
	"answer_question",
}


def _step(key: str, title: str, verifier: str, **configuration: Any) -> dict[str, Any]:
	return {"key": key, "title": title, "verifier": verifier, "configuration": configuration}


def lesson_version(lesson: dict[str, Any]) -> str:
	return str(lesson.get("version") or CATALOG_VERSION)


def lesson_versions(path: dict[str, Any]) -> dict[str, str]:
	return {lesson["key"]: lesson_version(lesson) for lesson in path["lessons"]}


def step_contract(step: dict[str, Any]) -> dict[str, Any]:
	"""Project a trusted catalogue step into the normalized public contract."""
	configuration = step["configuration"]
	tutorial = configuration.get("tutorial") or {}
	verifier = step["verifier"]
	step_type = tutorial.get("action") or {
		"event_document_submitted": "open_document",
		"capability_nonempty": "open_document",
		"report_available": "open_report",
		"run_validation_passed": "verify_report",
		"doctype_available": "explain",
	}.get(verifier, "inspect_value")
	if step_type not in STEP_TYPES:
		raise ValueError(f"Unsupported step type: {step_type}")

	if event_type := configuration.get("event_type"):
		binding = f"event:{_binding_key(event_type)}:first"
	elif capability := configuration.get("capability"):
		binding = f"capability:{capability}:first"
	elif report := configuration.get("report"):
		binding = f"report:{_binding_key(report)}"
	elif doctype := configuration.get("doctype"):
		binding = f"doctype:{_binding_key(doctype)}"
	elif verifier in {"company_exists", "company_accounts_exist", "party_links_exist"}:
		binding = "scenario:company"
	elif verifier == "fiscal_year_covers_run":
		binding = "scenario:fiscal_year"
	elif verifier == "return_source_exists":
		binding = "event:return_credit_note:first"
	else:
		binding = "scenario:run"

	return {
		"step_type": step_type,
		"binding": binding,
		"fieldname": tutorial.get("fieldname"),
	}


def _binding_key(value: str) -> str:
	return "_".join(str(value).strip().lower().replace("/", " ").replace("-", " ").split())


GLOSSARY = {
	"Chart of Accounts": {
		"simple": "The organized list of accounts used to classify every financial entry.",
		"advanced": "ERPNext groups ledger accounts by root type and enforces account-specific posting rules.",
	},
	"DocStatus": {
		"simple": "Whether a document is Draft, Submitted, or Cancelled.",
		"advanced": "Frappe stores these states as 0, 1, and 2. Submitted transactions usually affect ledgers.",
	},
	"General Ledger": {
		"simple": "The complete accounting record of debits and credits.",
		"advanced": "Every submitted voucher should balance to zero across its debit and credit entries.",
	},
	"Perpetual Inventory": {
		"simple": "Stock value is updated in accounting whenever inventory moves.",
		"advanced": "Stock Ledger Entries drive valuation while GL Entries recognize stock assets and cost of goods sold.",
	},
	"Receivable": {
		"simple": "Money that customers still owe the company.",
		"advanced": "Submitted Sales Invoices debit receivables; allocated Payment Entries reduce the outstanding balance.",
	},
	"Payable": {
		"simple": "Money that the company still owes suppliers.",
		"advanced": "Submitted Purchase Invoices credit payables; supplier payments reduce the outstanding balance.",
	},
	"Return Against": {
		"simple": "The original submitted document reversed by a return or credit note.",
		"advanced": "ERPNext preserves the audit chain through is_return and return_against instead of editing the original voucher.",
	},
	"Stock Ledger": {
		"simple": "The chronological record of item quantities and values by warehouse.",
		"advanced": "Backdated stock movements can trigger item-valuation reposting to keep later valuation layers consistent.",
	},
	"Fiscal Year": {
		"simple": "The accounting period used for annual financial reporting.",
		"advanced": "Posting dates, period closing, and retained earnings reporting depend on fiscal-year boundaries.",
	},
}


PATHS: tuple[dict[str, Any], ...] = (
	{
		"key": "foundations",
		"title": "Company and Accounting Foundations",
		"module": "Foundations",
		"description": "Understand the company, Chart of Accounts, fiscal year, opening capital, and opening stock.",
		"lessons": [
			{
				"key": "foundations-first-day",
				"title": "How the business starts",
				"summary": "Follow the company from configuration to funded, valued opening balances.",
				"steps": [
					_step("company", "Open the scenario company.", "company_exists", target="Company"),
					_step(
						"accounts",
						"Confirm that the company has a usable Chart of Accounts.",
						"company_accounts_exist",
						glossary="Chart of Accounts",
					),
					_step(
						"capital",
						"Inspect the opening-capital Journal Entry and its balanced ledger effect.",
						"event_document_submitted",
						event_type="Opening Capital",
						glossary="General Ledger",
					),
					_step(
						"opening-stock",
						"Inspect how initial inventory enters the stock and accounting ledgers.",
						"event_document_submitted",
						event_type="Opening Stock",
						glossary="Perpetual Inventory",
					),
				],
			}
		],
	},
	{
		"key": "crm-parties",
		"title": "CRM, Customers, Suppliers, and Contacts",
		"module": "CRM",
		"description": "See how leads, parties, contacts, and addresses support later transactions.",
		"lessons": [
			{
				"key": "crm-party-network",
				"title": "Meet the parties",
				"summary": "Inspect realistic prospects and trading partners with linked contact details.",
				"steps": [
					_step(
						"lead",
						"Open a generated lead.",
						"capability_nonempty",
						capability="erpnext.parties.leads",
					),
					_step(
						"customer",
						"Open a customer used by the selling lifecycle.",
						"capability_nonempty",
						capability="erpnext.parties.customers",
					),
					_step(
						"supplier",
						"Open a supplier used by the buying lifecycle.",
						"capability_nonempty",
						capability="erpnext.parties.suppliers",
					),
					_step(
						"contact",
						"Confirm that scenario-owned contacts and addresses exist.",
						"party_links_exist",
					),
				],
			}
		],
	},
	{
		"key": "buying",
		"title": "Buying and Payables",
		"module": "Buying",
		"description": "Follow a supplier commitment through receipt, invoice, and payment.",
		"lessons": [
			{
				"key": "buying-complete-cycle",
				"version": "1.0",
				"title": "Purchase to payment",
				"summary": "Trace one normal ERPNext buying lifecycle using linked submitted documents.",
				"steps": [
					_step(
						"orient",
						"Understand the purchase-to-payment story you are about to follow.",
						"event_document_submitted",
						event_type="Purchase Order",
						tutorial={"action": "explain"},
					),
					_step(
						"open-order",
						"Open the submitted Purchase Order commitment.",
						"event_document_submitted",
						event_type="Purchase Order",
					),
					_step(
						"inspect-supplier",
						"Inspect the supplier selected on the Purchase Order.",
						"event_document_submitted",
						event_type="Purchase Order",
						tutorial={"action": "highlight_field", "fieldname": "supplier"},
					),
					_step(
						"inspect-order-items",
						"Review the ordered products, quantities, rates, and required dates.",
						"event_document_submitted",
						event_type="Purchase Order",
						tutorial={"action": "highlight_field", "fieldname": "items"},
					),
					_step(
						"open-receipt",
						"Follow the order to its submitted Purchase Receipt.",
						"event_document_submitted",
						event_type="Purchase Receipt",
						glossary="Stock Ledger",
					),
					_step(
						"inspect-received-items",
						"Inspect the warehouse receipt quantities and values.",
						"event_document_submitted",
						event_type="Purchase Receipt",
						tutorial={"action": "highlight_field", "fieldname": "items"},
					),
					_step(
						"open-invoice",
						"Open the supplier's submitted Purchase Invoice.",
						"event_document_submitted",
						event_type="Purchase Invoice",
						glossary="Payable",
					),
					_step(
						"inspect-outstanding",
						"Inspect the payable and its outstanding amount.",
						"event_document_submitted",
						event_type="Purchase Invoice",
						tutorial={"action": "highlight_field", "fieldname": "outstanding_amount"},
					),
					_step(
						"open-payment",
						"Open the supplier Payment Entry allocated to the invoice.",
						"event_document_submitted",
						event_type="Supplier Payment",
					),
					_step(
						"verify-payment",
						"Verify the submitted payment that completes purchase to payment.",
						"event_document_submitted",
						event_type="Supplier Payment",
						tutorial={"action": "verify_document"},
					),
				],
			}
		],
	},
	{
		"key": "selling",
		"title": "Selling and Receivables",
		"module": "Selling",
		"description": "Follow customer demand through delivery, billing, and collection.",
		"lessons": [
			{
				"key": "selling-complete-cycle",
				"version": "1.0",
				"title": "Order to cash",
				"summary": "Trace one linked ERPNext selling lifecycle and its operational and ledger effects.",
				"steps": [
					_step(
						"orient",
						"Understand the order-to-cash story you are about to follow.",
						"event_document_submitted",
						event_type="Sales Order",
						tutorial={"action": "explain"},
					),
					_step(
						"open-order",
						"Open the customer's submitted Sales Order.",
						"event_document_submitted",
						event_type="Sales Order",
						tutorial={"action": "open_document"},
					),
					_step(
						"inspect-customer",
						"Inspect the customer selected on the Sales Order.",
						"event_document_submitted",
						event_type="Sales Order",
						tutorial={
							"action": "highlight_field",
							"fieldname": "customer",
						},
					),
					_step(
						"inspect-order-items",
						"Review the products, quantities, rates, and promised delivery dates.",
						"event_document_submitted",
						event_type="Sales Order",
						tutorial={
							"action": "highlight_field",
							"fieldname": "items",
						},
					),
					_step(
						"open-delivery",
						"Follow fulfillment to the submitted Delivery Note.",
						"event_document_submitted",
						event_type="Delivery Note",
						glossary="Stock Ledger",
						tutorial={"action": "open_document"},
					),
					_step(
						"inspect-warehouse",
						"See which warehouse supplied the delivered items.",
						"event_document_submitted",
						event_type="Delivery Note",
						tutorial={
							"action": "highlight_field",
							"fieldname": "items",
						},
					),
					_step(
						"open-invoice",
						"Open the linked Sales Invoice and its receivable.",
						"event_document_submitted",
						event_type="Sales Invoice",
						glossary="Receivable",
						tutorial={"action": "open_document"},
					),
					_step(
						"inspect-outstanding",
						"Inspect the invoice total and remaining outstanding amount.",
						"event_document_submitted",
						event_type="Sales Invoice",
						tutorial={
							"action": "highlight_field",
							"fieldname": "outstanding_amount",
						},
					),
					_step(
						"open-payment",
						"Open the customer Payment Entry allocated to the invoice.",
						"event_document_submitted",
						event_type="Customer Payment",
						tutorial={"action": "open_document"},
					),
					_step(
						"verify-collection",
						"Verify the submitted collection that completes order to cash.",
						"event_document_submitted",
						event_type="Customer Payment",
						tutorial={"action": "verify_document"},
					),
				],
			}
		],
	},
	{
		"key": "stock",
		"title": "Stock and Valuation",
		"module": "Stock",
		"description": "Understand receipts, deliveries, warehouses, quantities, and valuation.",
		"lessons": [
			{
				"key": "stock-movement",
				"title": "Why stock changes",
				"summary": "Compare incoming and outgoing stock movements and inspect Stock Balance.",
				"steps": [
					_step(
						"incoming",
						"Inspect a submitted Purchase Receipt.",
						"event_document_submitted",
						event_type="Purchase Receipt",
					),
					_step(
						"outgoing",
						"Inspect a submitted Delivery Note.",
						"event_document_submitted",
						event_type="Delivery Note",
					),
					_step(
						"balance",
						"Open the Stock Balance report.",
						"report_available",
						report="Stock Balance",
						glossary="Stock Ledger",
					),
				],
			}
		],
	},
	{
		"key": "accounting",
		"title": "Receivables, Payables, and Payments",
		"module": "Accounts",
		"description": "Connect invoices, outstanding balances, payments, accruals, and the General Ledger.",
		"lessons": [
			{
				"key": "accounting-balances",
				"title": "Read the books",
				"summary": "Verify that generated business activity produced coherent accounting evidence.",
				"steps": [
					_step(
						"receivable",
						"Inspect Accounts Receivable.",
						"report_available",
						report="Accounts Receivable",
						glossary="Receivable",
					),
					_step(
						"payable",
						"Inspect Accounts Payable.",
						"report_available",
						report="Accounts Payable",
						glossary="Payable",
					),
					_step(
						"ledger",
						"Open the General Ledger.",
						"report_available",
						report="General Ledger",
						glossary="General Ledger",
					),
					_step(
						"validated",
						"Confirm that the scenario books pass validation.",
						"run_validation_passed",
					),
				],
			}
		],
	},
	{
		"key": "returns",
		"title": "Returns and Credit Notes",
		"module": "Selling",
		"description": "Understand reversal documents without rewriting the original audit trail.",
		"lessons": [
			{
				"key": "returns-audit-chain",
				"title": "Reverse a sale correctly",
				"summary": "Inspect a generated return or credit note and its original document.",
				"steps": [
					_step(
						"return",
						"Open a submitted return or credit note.",
						"event_document_submitted",
						event_type="Return / Credit Note",
						glossary="Return Against",
					),
					_step(
						"source",
						"Verify that the return links to its original submitted document.",
						"return_source_exists",
					),
				],
			}
		],
	},
	{
		"key": "reports",
		"title": "Operational and Financial Reports",
		"module": "Reports",
		"description": "Use standard ERPNext reports as views over the generated records.",
		"lessons": [
			{
				"key": "reports-evidence",
				"title": "Move from documents to reports",
				"summary": "Open the reports used to understand sales, balances, and stock.",
				"steps": [
					_step(
						"receivables",
						"Open Accounts Receivable.",
						"report_available",
						report="Accounts Receivable",
					),
					_step(
						"payables", "Open Accounts Payable.", "report_available", report="Accounts Payable"
					),
					_step("stock", "Open Stock Balance.", "report_available", report="Stock Balance"),
					_step("trial", "Open Trial Balance.", "report_available", report="Trial Balance"),
				],
			}
		],
	},
	{
		"key": "period-closing",
		"title": "Fiscal Period and Closing Foundations",
		"module": "Accounts",
		"description": "Prepare to review a period before using ERPNext's closing documents.",
		"lessons": [
			{
				"key": "closing-readiness",
				"title": "Review before closing",
				"summary": "Confirm fiscal-year configuration, accruals, and the reports used before period closing.",
				"steps": [
					_step(
						"fiscal",
						"Confirm a fiscal year covers the scenario dates.",
						"fiscal_year_covers_run",
						glossary="Fiscal Year",
					),
					_step(
						"accrual",
						"Inspect a period-end operating accrual.",
						"event_document_submitted",
						event_type="Operating Accrual",
					),
					_step(
						"trial",
						"Review Trial Balance before closing.",
						"report_available",
						report="Trial Balance",
					),
					_step(
						"doctype",
						"Confirm ERPNext's Period Closing Voucher is available.",
						"doctype_available",
						doctype="Period Closing Voucher",
					),
				],
			}
		],
	},
)


def get_path(path_key: str) -> dict[str, Any]:
	for path in PATHS:
		if path["key"] == path_key:
			return path
	raise KeyError(path_key)


def get_step(path_key: str, lesson_key: str, step_key: str) -> dict[str, Any]:
	path = get_path(path_key)
	for lesson in path["lessons"]:
		if lesson["key"] != lesson_key:
			continue
		for step in lesson["steps"]:
			if step["key"] == step_key:
				return step
	raise KeyError(f"{path_key}/{lesson_key}/{step_key}")


def flatten_steps(path: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
	return [(lesson["key"], step) for lesson in path["lessons"] for step in lesson["steps"]]
