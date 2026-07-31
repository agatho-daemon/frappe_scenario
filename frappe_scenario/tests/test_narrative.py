# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Deterministic scenario narrative compilation."""

from __future__ import annotations

import datetime

import pytest

from frappe_scenario.core.narrative import compile_scenario_events

pytestmark = pytest.mark.pure


def test_events_are_chronological_and_preserve_real_lifecycle_links():
	events = compile_scenario_events(
		{
			"erpnext.selling.sales_invoices": [
				{
					"name": "SINV-1",
					"customer": "Al Noor Trading",
					"delivery_note": "DN-1",
					"posting_date": "2026-01-12",
					"channel": "credit",
				}
			],
			"erpnext.selling.sales_orders": [
				{
					"name": "SO-1",
					"customer": "Al Noor Trading",
					"order_date": "2026-01-10",
				}
			],
			"erpnext.selling.delivery_notes": [
				{
					"name": "DN-1",
					"sales_order": "SO-1",
					"customer": "Al Noor Trading",
					"posting_date": "2026-01-11",
					"partial": True,
				}
			],
		},
		fallback_date=datetime.date(2026, 1, 31),
	)

	assert [event["event_type"] for event in events] == [
		"Sales Order",
		"Delivery Note",
		"Sales Invoice",
	]
	assert {tuple(link.values()) for link in events[1]["related_documents"]} == {
		("Delivery Note", "DN-1"),
		("Sales Order", "SO-1"),
	}
	assert "remains open" in events[1]["stock_effect"]


def test_explanations_cover_operations_ledger_stock_and_cancellation():
	[event] = compile_scenario_events(
		{
			"erpnext.accounts.customer_payments": [
				{
					"name": "PAY-1",
					"invoice": "SINV-1",
					"invoice_doctype": "Sales Invoice",
					"posting_date": "2026-01-20",
				}
			]
		},
		fallback_date="2026-01-31",
	)

	assert event["why"]
	assert "receivable" in event["operational_effect"].lower()
	assert "debited" in event["ledger_effect"].lower()
	assert "no stock" in event["stock_effect"].lower()
	assert "cancellation" in event["cancellation_consequence"].lower()
	assert {tuple(link.values()) for link in event["related_documents"]} == {
		("Payment Entry", "PAY-1"),
		("Sales Invoice", "SINV-1"),
	}
