# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Presentation-ready facts derived from a completed scenario run."""

from __future__ import annotations

from typing import Any

import frappe

from frappe_scenario.providers.erpnext_buying import INVOICES as PURCHASE_INVOICES
from frappe_scenario.providers.erpnext_buying import RETURNS as PURCHASE_RETURNS
from frappe_scenario.providers.erpnext_catalog import ITEMS
from frappe_scenario.providers.erpnext_commercial import CRM, TRANSFERS
from frappe_scenario.providers.erpnext_parties import CUSTOMERS, LEADS, SUPPLIERS
from frappe_scenario.providers.erpnext_payments import (
	ACCRUALS,
	BANK_RECONCILIATION,
	PAYMENTS,
	PERIOD_CLOSING,
	RECEIPTS,
)
from frappe_scenario.providers.erpnext_selling import INVOICES as SALES_INVOICES
from frappe_scenario.providers.erpnext_selling import RETURNS


def build_outcome_summary(context: Any) -> dict[str, Any]:
	"""Summarise actual post-payment balances and useful ERPNext report routes."""
	sales = _document_totals("Sales Invoice", context.optional(SALES_INVOICES) or [])
	purchases = _document_totals("Purchase Invoice", context.optional(PURCHASE_INVOICES) or [])
	returns = context.optional(RETURNS) or []
	purchase_returns = context.optional(PURCHASE_RETURNS) or []
	crm = context.optional(CRM) or {}
	return {
		"master_data": {
			"customers": len(context.optional(CUSTOMERS) or []),
			"suppliers": len(context.optional(SUPPLIERS) or []),
			"leads": len(context.optional(LEADS) or []),
			"items": len(context.optional(ITEMS) or []),
		},
		"selling": {
			"invoice_count": len(sales),
			"invoiced": round(sum(row["grand_total"] for row in sales), 2),
			"outstanding": round(sum(row["outstanding_amount"] for row in sales), 2),
			"return_documents": len(returns),
		},
		"buying": {
			"invoice_count": len(purchases),
			"invoiced": round(sum(row["grand_total"] for row in purchases), 2),
			"outstanding": round(sum(row["outstanding_amount"] for row in purchases), 2),
			"return_documents": len(purchase_returns),
		},
		"commercial": {
			"opportunities": len(crm.get("opportunities") or []),
			"quotations": len(crm.get("quotations") or []),
			"stock_transfers": len(context.optional(TRANSFERS) or []),
		},
		"accounting": {
			"customer_receipts": len(context.optional(RECEIPTS) or []),
			"supplier_payments": len(context.optional(PAYMENTS) or []),
			"accrual_journals": len(context.optional(ACCRUALS) or []),
			"reconciled_bank_transactions": len(context.optional(BANK_RECONCILIATION) or []),
			"period_closings": len(context.optional(PERIOD_CLOSING) or []),
		},
		"reports": [
			{"label": "General Ledger", "route": "/app/query-report/General Ledger"},
			{"label": "Accounts Receivable", "route": "/app/query-report/Accounts Receivable"},
			{"label": "Accounts Payable", "route": "/app/query-report/Accounts Payable"},
			{"label": "Stock Balance", "route": "/app/query-report/Stock Balance"},
			{"label": "Profit and Loss Statement", "route": "/app/query-report/Profit and Loss Statement"},
			{"label": "Opportunity Summary", "route": "/app/query-report/Opportunity Summary by Sales Stage"},
			{"label": "Bank Reconciliation", "route": "/app/bank-reconciliation-tool"},
		],
	}


def _document_totals(doctype: str, entries: list[dict[str, Any]]) -> list[dict[str, float]]:
	rows: list[dict[str, float]] = []
	for entry in entries:
		values = frappe.db.get_value(
			doctype,
			entry["name"],
			["grand_total", "outstanding_amount"],
			as_dict=True,
		)
		if values:
			rows.append(
				{
					"grand_total": float(values.grand_total or 0),
					"outstanding_amount": float(values.outstanding_amount or 0),
				}
			)
	return rows
