# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Closed, versioned catalogue for the ERPNext Troubleshooting Lab."""

from __future__ import annotations

from typing import Any

CATALOG_VERSION = "1.0"


def _problem(
	key: str,
	title: str,
	module: str,
	difficulty: str,
	objective: str,
	injector: str,
	accepted_diagnosis: str,
	choices: list[tuple[str, str]],
	hints: list[str],
) -> dict[str, Any]:
	return {
		"key": key,
		"title": title,
		"module": module,
		"difficulty": difficulty,
		"objective": objective,
		"injector": injector,
		"accepted_diagnosis": accepted_diagnosis,
		"choices": [{"key": choice_key, "label": label} for choice_key, label in choices],
		"hints": hints,
	}


PROBLEMS: tuple[dict[str, Any], ...] = (
	_problem(
		"unreconciled-payment",
		"The payment that did not settle an invoice",
		"Accounts",
		"Everyday Business",
		"Inspect the draft receipt and explain why the customer's invoice is still outstanding.",
		"unallocated_payment",
		"missing-allocation",
		[
			("wrong-account", "The receipt used an expense account."),
			("missing-allocation", "The Payment Entry has no invoice allocation."),
			("exchange-rate", "The exchange rate changed after posting."),
		],
		["Compare the Payment Entry References table with the invoice outstanding amount."],
	),
	_problem(
		"overdue-account",
		"The customer who paid late",
		"Accounts",
		"Essentials",
		"Find the overdue receivable and distinguish its due date from its posting date.",
		"observe_overdue",
		"past-due-outstanding",
		[
			("draft-invoice", "The invoice is still a draft."),
			("past-due-outstanding", "The invoice is submitted, unpaid, and past its due date."),
			("future-delivery", "The delivery date is in the future."),
		],
		["Open Accounts Receivable and compare due date, age, and outstanding amount."],
	),
	_problem(
		"partial-delivery",
		"The sales order that is not fully delivered",
		"Selling",
		"Essentials",
		"Trace the remaining quantity from Sales Order to Delivery Note.",
		"observe_partial_delivery",
		"remaining-quantity",
		[
			("remaining-quantity", "Only part of the ordered quantity was delivered."),
			("invoice-cancelled", "The invoice was cancelled."),
			("warehouse-disabled", "The warehouse was disabled."),
		],
		["Compare ordered quantity with delivered quantity on the source Sales Order."],
	),
	_problem(
		"stock-shortage",
		"The order that exceeds available stock",
		"Stock",
		"Everyday Business",
		"Review the draft order and identify why it cannot be fulfilled from current stock.",
		"excess_sales_order",
		"insufficient-available-stock",
		[
			("insufficient-available-stock", "The requested stock quantity exceeds the available balance."),
			("missing-customer", "The order has no customer."),
			("tax-template", "The wrong tax template was selected."),
		],
		["Compare the first stock item quantity with Stock Balance for its warehouse."],
	),
	_problem(
		"pricing-error",
		"The implausibly cheap item",
		"Selling",
		"Everyday Business",
		"Find the price-list entry that produces an implausible margin.",
		"low_item_price",
		"price-below-cost",
		[
			("price-below-cost", "The selling price was set below the item's expected cost."),
			("wrong-uom", "The stock UOM is missing."),
			("inactive-customer", "The customer is disabled."),
		],
		["Compare the affected Item Price with the scenario's buying price."],
	),
	_problem(
		"credit-limit-breach",
		"The customer beyond its credit limit",
		"Selling",
		"Complex Operations",
		"Explain why the proposed sale should be held for this customer.",
		"low_credit_limit",
		"exposure-exceeds-limit",
		[
			(
				"exposure-exceeds-limit",
				"Existing receivables plus the proposed sale exceed the configured company credit limit.",
			),
			("territory-mismatch", "The customer belongs to another territory."),
			("missing-contact", "The customer has no primary contact."),
		],
		["Inspect the customer credit-limit row, Accounts Receivable, and the proposed Sales Order total."],
	),
	_problem(
		"posting-period",
		"The voucher outside an open fiscal period",
		"Accounts",
		"Complex Operations",
		"Determine why the proposed posting date is not valid for the configured fiscal periods.",
		"observe_posting_period",
		"date-outside-fiscal-year",
		[
			("date-outside-fiscal-year", "No active Fiscal Year covers the proposed posting date."),
			("unbalanced-entry", "The existing Journal Entry is unbalanced."),
			("missing-party", "A receivable row has no party."),
		],
		["Compare the proposed date in the case evidence with active Fiscal Year boundaries."],
	),
)


def get_problem(problem_key: str) -> dict[str, Any]:
	for problem in PROBLEMS:
		if problem["key"] == problem_key:
			return problem
	raise KeyError(problem_key)
