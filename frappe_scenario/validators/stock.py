# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Stock integrity validators."""

from __future__ import annotations

import frappe
from frappe.query_builder import DocType
from frappe.query_builder.functions import Sum

from frappe_scenario.core.context import ScenarioContext
from frappe_scenario.core.validation import ValidationResult
from frappe_scenario.providers.erpnext_foundation import ACCOUNTS, COMPANY
from frappe_scenario.validators.ledger import REPORT_LIMIT, account_balance

#: Perpetual inventory rounds per transaction, so allow a small absolute drift.
VALUATION_TOLERANCE = 1.0
VALUATION_RELATIVE_TOLERANCE = 0.001


def valuation_tolerance(stock_value: float) -> float:
	"""Return a conservative rounding allowance for the inventory population."""
	return max(VALUATION_TOLERANCE, abs(stock_value) * VALUATION_RELATIVE_TOLERANCE)


def validate_non_negative_stock(context: ScenarioContext) -> ValidationResult:
	"""Backdated postings must never drive a warehouse balance below zero."""
	result = ValidationResult()
	company = context.optional(COMPANY)
	if not company:
		return result

	negatives = frappe.get_all(
		"Stock Ledger Entry",
		filters={
			"company": company,
			"is_cancelled": 0,
			"qty_after_transaction": ("<", 0),
		},
		fields=[
			"item_code",
			"warehouse",
			"posting_date",
			"qty_after_transaction",
			"voucher_type",
			"voucher_no",
		],
		limit=REPORT_LIMIT,
	)
	for entry in negatives:
		result.error(
			rule="stock.non_negative",
			message=(
				f"{entry.item_code} in {entry.warehouse} falls to {entry.qty_after_transaction} on "
				f"{entry.posting_date} via {entry.voucher_type} {entry.voucher_no}."
			),
			doctype=entry.voucher_type,
			record=entry.voucher_no,
			observed=float(entry.qty_after_transaction),
			expected=">= 0",
			remediation="Increase opening stock cover or reduce sales quantities for this item.",
		)

	bins = frappe.get_all(
		"Bin",
		filters={"actual_qty": ("<", 0)},
		fields=["item_code", "warehouse", "actual_qty"],
		limit=REPORT_LIMIT,
	)
	for row in bins:
		result.error(
			rule="stock.non_negative",
			message=f"{row.item_code} closes at {row.actual_qty} in {row.warehouse}.",
			doctype="Bin",
			record=f"{row.item_code} @ {row.warehouse}",
			observed=float(row.actual_qty),
			expected=">= 0",
		)
	return result


def validate_stock_valuation(context: ScenarioContext) -> ValidationResult:
	"""Under perpetual inventory the stock account must match the stock value."""
	result = ValidationResult()
	company = context.optional(COMPANY)
	accounts = context.optional(ACCOUNTS) or {}
	if not company:
		return result

	if not frappe.db.get_value("Company", company, "enable_perpetual_inventory"):
		result.info(
			rule="stock.valuation_matches_accounts",
			message="Perpetual inventory is disabled, so stock value is not reconciled to the ledger.",
			doctype="Company",
			record=company,
		)
		return result

	stock_account = accounts.get("stock_in_hand")
	if not stock_account:
		result.warning(
			rule="stock.valuation_matches_accounts",
			message="No stock-in-hand account was resolved, so stock value cannot be reconciled.",
			doctype="Company",
			record=company,
		)
		return result

	warehouses = frappe.get_all("Warehouse", filters={"company": company, "is_group": 0}, pluck="name")
	if not warehouses:
		return result

	bin_table = DocType("Bin")
	rows = (
		frappe.qb.from_(bin_table)
		.select(Sum(bin_table.stock_value).as_("value"))
		.where(bin_table.warehouse.isin(warehouses))
		.run(as_dict=True)
	)
	stock_value = float(rows[0].value or 0) if rows else 0.0
	ledger_value = account_balance(company, stock_account)

	if abs(stock_value - ledger_value) > valuation_tolerance(stock_value):
		result.error(
			rule="stock.valuation_matches_accounts",
			message=(f"Stock is valued at {stock_value:.2f} but {stock_account} carries {ledger_value:.2f}."),
			doctype="Account",
			record=stock_account,
			observed=round(stock_value, 2),
			expected=round(ledger_value, 2),
			remediation="Check for stock transactions posted without an inventory account.",
		)
	return result
