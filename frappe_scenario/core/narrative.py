# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Deterministic business narrative derived from published ERPNext records."""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from typing import Any

import frappe


@dataclass(frozen=True)
class EventKind:
	capability: str
	event_type: str
	doctype: str
	date_fields: tuple[str, ...]
	name_fields: tuple[str, ...]


KINDS = (
	EventKind("erpnext.opening.stock", "Opening Stock", "Stock Entry", ("posting_date",), ("stock_entry",)),
	EventKind(
		"erpnext.opening.capital",
		"Opening Capital",
		"Journal Entry",
		("posting_date",),
		("journal_entry",),
	),
	EventKind(
		"erpnext.buying.purchase_orders", "Purchase Order", "Purchase Order", ("order_date",), ("name",)
	),
	EventKind(
		"erpnext.buying.purchase_receipts",
		"Purchase Receipt",
		"Purchase Receipt",
		("posting_date",),
		("name",),
	),
	EventKind(
		"erpnext.buying.purchase_invoices",
		"Purchase Invoice",
		"Purchase Invoice",
		("posting_date",),
		("name",),
	),
	EventKind("erpnext.selling.sales_orders", "Sales Order", "Sales Order", ("order_date",), ("name",)),
	EventKind(
		"erpnext.selling.delivery_notes",
		"Delivery Note",
		"Delivery Note",
		("posting_date",),
		("name",),
	),
	EventKind(
		"erpnext.selling.sales_invoices",
		"Sales Invoice",
		"Sales Invoice",
		("posting_date",),
		("name",),
	),
	EventKind("erpnext.selling.returns", "Return / Credit Note", "", ("posting_date",), ("name",)),
	EventKind(
		"erpnext.accounts.customer_payments",
		"Customer Payment",
		"Payment Entry",
		("posting_date",),
		("name",),
	),
	EventKind(
		"erpnext.accounts.supplier_payments",
		"Supplier Payment",
		"Payment Entry",
		("posting_date",),
		("name",),
	),
	EventKind(
		"erpnext.accounts.accruals",
		"Operating Accrual",
		"Journal Entry",
		("posting_date",),
		("name",),
	),
)


def build_scenario_events(run: Any, capabilities: dict[str, Any]) -> list[str]:
	"""Replace the run's narrative with a chronological set of linked events."""
	frappe.db.delete("Scenario Event", {"scenario_run": run.name})
	candidates = compile_scenario_events(capabilities, fallback_date=run.anchor_date)
	names: list[str] = []
	for sequence, entry in enumerate(candidates, start=1):
		doc = frappe.get_doc(
			{
				"doctype": "Scenario Event",
				"scenario_run": run.name,
				"sequence": sequence,
				**entry,
				"related_documents": json.dumps(entry["related_documents"], indent="\t"),
			}
		).insert(ignore_permissions=True)
		names.append(doc.name)

	for index, name in enumerate(names):
		frappe.db.set_value(
			"Scenario Event",
			name,
			{
				"previous_event": names[index - 1] if index else None,
				"next_event": names[index + 1] if index + 1 < len(names) else None,
			},
			update_modified=False,
		)
	run.db_set("event_count", len(names), update_modified=False)
	return names


def compile_scenario_events(
	capabilities: dict[str, Any],
	*,
	fallback_date: datetime.date | str,
) -> list[dict[str, Any]]:
	"""Compile stable event payloads without writing to Frappe."""
	candidates: list[dict[str, Any]] = []
	for kind in KINDS:
		value = capabilities.get(kind.capability)
		entries = value if isinstance(value, list) else [value] if isinstance(value, dict) else []
		for entry in entries:
			name = _first(entry, kind.name_fields)
			if not name:
				continue
			doctype = entry.get("doctype") or kind.doctype
			if not doctype:
				continue
			event_date = _event_date(entry, kind.date_fields, fallback_date)
			related = _related_documents(doctype, name, entry)
			effects = _effects(kind.event_type, entry)
			candidates.append(
				{
					"event_date": event_date,
					"event_type": kind.event_type,
					"title": _title(kind.event_type, entry, name),
					"summary": effects["why"],
					"reference_doctype": doctype,
					"reference_name": name,
					"related_documents": related,
					**effects,
				}
			)

	candidates.sort(
		key=lambda entry: (
			entry["event_date"],
			_next_rank(entry["event_type"]),
			entry["reference_doctype"],
			entry["reference_name"],
		)
	)
	return candidates


def story_for_run(run_name: str) -> dict[str, Any]:
	run = frappe.get_doc("Scenario Run", run_name)
	run.check_permission("read")
	events = frappe.get_all(
		"Scenario Event",
		filters={"scenario_run": run.name},
		fields=[
			"name",
			"sequence",
			"event_date",
			"event_type",
			"title",
			"summary",
			"reference_doctype",
			"reference_name",
			"previous_event",
			"next_event",
		],
		order_by="sequence asc",
	)
	return {
		"run": {"name": run.name, "title": run.title, "company": run.company, "status": run.status},
		"events": [dict(event) for event in events],
	}


def explain_record(run_name: str, doctype: str, name: str) -> dict[str, Any]:
	"""Explain one generated record using only deterministic scenario evidence."""
	story = story_for_run(run_name)
	events = frappe.get_all(
		"Scenario Event",
		filters={"scenario_run": run_name},
		fields=["*"],
		order_by="sequence asc",
	)
	match = None
	for event in events:
		related = json.loads(event.related_documents or "[]")
		if (event.reference_doctype == doctype and event.reference_name == name) or any(
			entry.get("doctype") == doctype and entry.get("name") == name for entry in related
		):
			match = event
			break
	if not match:
		frappe.throw("This record is not part of the selected scenario narrative.", frappe.DoesNotExistError)
	return {
		"run": story["run"],
		"event": {
			"name": match.name,
			"sequence": match.sequence,
			"event_date": str(match.event_date),
			"event_type": match.event_type,
			"title": match.title,
			"why": match.why,
			"operational_effect": match.operational_effect,
			"ledger_effect": match.ledger_effect,
			"stock_effect": match.stock_effect,
			"cancellation_consequence": match.cancellation_consequence,
			"related_documents": json.loads(match.related_documents or "[]"),
			"previous_event": match.previous_event,
			"next_event": match.next_event,
		},
	}


def discard_scenario_events(run_name: str) -> None:
	frappe.db.delete("Scenario Event", {"scenario_run": run_name})
	frappe.db.set_value("Scenario Run", run_name, "event_count", 0, update_modified=False)


def _event_date(entry: dict[str, Any], fields: tuple[str, ...], fallback: Any) -> datetime.date:
	value = _first(entry, fields) or fallback
	if isinstance(value, datetime.datetime):
		return value.date()
	if isinstance(value, datetime.date):
		return value
	return datetime.date.fromisoformat(str(value)[:10])


def _first(entry: dict[str, Any], fields: tuple[str, ...]) -> Any:
	return next((entry.get(field) for field in fields if entry.get(field)), None)


def _related_documents(doctype: str, name: str, entry: dict[str, Any]) -> list[dict[str, str]]:
	related = [{"doctype": doctype, "name": name}]
	links = {
		"sales_order": "Sales Order",
		"delivery_note": "Delivery Note",
		"purchase_order": "Purchase Order",
		"purchase_receipt": "Purchase Receipt",
		"invoice": entry.get("invoice_doctype") or "Sales Invoice",
		"return_against": doctype,
	}
	for field, linked_doctype in links.items():
		if entry.get(field):
			related.append({"doctype": linked_doctype, "name": str(entry[field])})
	return related


def _title(event_type: str, entry: dict[str, Any], name: str) -> str:
	party = entry.get("customer") or entry.get("supplier")
	return f"{event_type}: {party or name}"


def _effects(event_type: str, entry: dict[str, Any]) -> dict[str, str]:
	partial = bool(entry.get("partial"))
	templates = {
		"Opening Stock": (
			"The business received its initial inventory so selling can begin.",
			"Stock becomes available in the opening warehouse.",
			"Perpetual inventory records the stock asset against opening adjustment.",
			"Quantity and valuation increase for every received stock item.",
			"Cancellation removes the opening quantities and may invalidate every later stock movement.",
		),
		"Opening Capital": (
			"The owners funded the company before trading activity began.",
			"Working cash becomes available to pay suppliers and expenses.",
			"Bank is debited and owners' equity is credited by equal amounts.",
			"There is no stock movement.",
			"Cancellation removes the opening cash and equity entry and can leave later payments unfunded.",
		),
		"Purchase Order": (
			"Inventory demand triggered a commitment to a supplier.",
			"The supplier, expected quantities, prices, and delivery schedule are agreed.",
			"A purchase order normally creates no general-ledger posting.",
			"No stock moves until a Purchase Receipt is submitted.",
			"Downstream receipts and invoices must be cancelled before this order can be cancelled.",
		),
		"Purchase Receipt": (
			"The supplier delivered goods against an approved purchase order.",
			"Received quantities become available for operations.",
			"Perpetual inventory updates stock value and stock received but not billed.",
			"Stock quantity increases; a partial receipt leaves the order open."
			if partial
			else "Stock quantity increases for the received lines.",
			"Cancellation reverses stock and valuation; dependent purchase invoices must be handled first.",
		),
		"Purchase Invoice": (
			"The supplier billed the company for received goods.",
			"A payable is created and becomes eligible for payment.",
			"The payable and received-not-billed or expense accounts are posted.",
			"Stock quantity does not move; valuation may be adjusted by ERPNext.",
			"A return or debit note reverses the liability; payments must be reconciled or cancelled first.",
		),
		"Sales Order": (
			"A customer accepted the commercial offer and placed an order.",
			"Demand, promised quantities, prices, and delivery dates are recorded.",
			"A sales order normally creates no general-ledger posting.",
			"Projected stock changes, but actual stock does not move yet.",
			"Delivery Notes and invoices must be cancelled before the order can be cancelled.",
		),
		"Delivery Note": (
			"The company fulfilled all or part of a customer's sales order.",
			"Delivered quantities become billable and customer fulfillment is updated.",
			"With perpetual inventory, stock asset and cost of goods sold are posted.",
			"Stock decreases; the order remains open when delivery is partial."
			if partial
			else "Stock decreases by the delivered quantities.",
			"A return reverses the stock movement; downstream invoices must be handled before cancellation.",
		),
		"Sales Invoice": (
			"Delivered goods or a counter sale were billed to the customer.",
			"Revenue and the customer's outstanding balance are recognized.",
			"Receivable, income, tax, and rounding accounts are posted as applicable.",
			"A counter invoice moves stock; a delivery-based invoice normally does not move it again.",
			"A credit note reverses the invoice; allocated payments must be reconciled or cancelled first.",
		),
		"Customer Payment": (
			"The customer settled all or part of an outstanding invoice.",
			"The receivable balance and ageing position decrease.",
			"Bank or cash is debited and accounts receivable is credited.",
			"There is no stock movement.",
			"Cancellation restores the invoice outstanding amount and removes the cash posting.",
		),
		"Supplier Payment": (
			"The company settled all or part of a supplier invoice.",
			"The payable balance and ageing position decrease.",
			"Accounts payable is debited and bank or cash is credited.",
			"There is no stock movement.",
			"Cancellation restores the payable and reverses the bank posting.",
		),
		"Return / Credit Note": (
			"Goods or value were returned against an earlier customer document.",
			"Fulfillment or the customer's balance is reduced against the original transaction.",
			"A credit note reverses revenue, tax, and receivable as applicable.",
			"A Delivery Note return restores stock; an invoice-only credit note does not.",
			"Cancellation reinstates the original sale effect and removes the return adjustment.",
		),
		"Operating Accrual": (
			"A recurring operating cost was recognized in the period it belongs to.",
			"Management reports include the cost before cash is paid.",
			"Operating expense is debited and accrued liability is credited.",
			"There is no stock movement.",
			"Cancellation removes both the expense and accrued liability from the period.",
		),
	}
	why, operational, ledger, stock, cancellation = templates[event_type]
	return {
		"why": why,
		"operational_effect": operational,
		"ledger_effect": ledger,
		"stock_effect": stock,
		"cancellation_consequence": cancellation,
	}


def _next_rank(event_type: str) -> int:
	return next((index for index, kind in enumerate(KINDS) if kind.event_type == event_type), len(KINDS))
