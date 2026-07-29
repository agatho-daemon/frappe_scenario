# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Commercial plausibility validators.

A dataset can be perfectly balanced and still be useless: zero margin, no
activity, or every sale to one customer. These validators check that the numbers
tell the story the specification asked for.
"""

from __future__ import annotations

from frappe_scenario.core.context import ScenarioContext
from frappe_scenario.core.validation import ValidationResult
from frappe_scenario.providers.erpnext_buying import ORDERS as PURCHASE_ORDERS
from frappe_scenario.providers.erpnext_selling import INVOICES as SALES_INVOICES
from frappe_scenario.providers.erpnext_selling import ORDERS as SALES_ORDERS


def validate_gross_margin(context: ScenarioContext) -> ValidationResult:
	"""Realised gross margin must sit inside the requested band."""
	result = ValidationResult()
	invoices = context.optional(SALES_INVOICES) or []
	priced = [invoice for invoice in invoices if invoice.get("cost_basis")]
	if not priced:
		return result

	revenue = sum(float(invoice["grand_total"]) for invoice in priced)
	cost = sum(float(invoice["cost_basis"]) for invoice in priced)
	if revenue <= 0:
		result.error(
			rule="plausibility.gross_margin",
			message="Sales invoices total zero revenue.",
			doctype="Sales Invoice",
			observed=revenue,
		)
		return result

	margin = (revenue - cost) / revenue
	# ``gross_margin_range`` is a two element ``[low, high]`` array in the schema.
	band = context.section("catalog").get("gross_margin_range") or [0.0, 1.0]
	band_low, band_high = float(band[0]), float(band[1])
	tolerance = float(context.section("validation").get("margin_tolerance") or 0.05)
	low = band_low - tolerance
	high = band_high + tolerance

	if margin < low or margin > high:
		result.warning(
			rule="plausibility.gross_margin",
			message=(
				f"Realised gross margin is {margin:.1%}, outside the requested band of "
				f"{band_low:.1%} to {band_high:.1%}."
			),
			doctype="Sales Invoice",
			observed=round(margin, 4),
			expected=f"{low:.4f} .. {high:.4f}",
			remediation="Adjust catalog.gross_margin_range or the selling discount options.",
		)
	else:
		result.info(
			rule="plausibility.gross_margin",
			message=f"Realised gross margin is {margin:.1%} on {revenue:.2f} of invoiced revenue.",
			doctype="Sales Invoice",
			observed=round(margin, 4),
		)
	return result


def validate_activity_present(context: ScenarioContext) -> ValidationResult:
	"""If the specification asked for trading activity, it must exist."""
	result = ValidationResult()
	operations = context.section("operations")

	expectations = (
		("operations.sales_orders_per_month", SALES_ORDERS, "Sales Order"),
		("operations.purchase_orders_per_month", PURCHASE_ORDERS, "Purchase Order"),
	)
	for path, capability, doctype in expectations:
		requested = int(operations.get(path.rsplit(".", 1)[-1]) or 0)
		produced = len(context.optional(capability) or [])
		if requested > 0 and produced == 0:
			result.error(
				rule="plausibility.activity_present",
				message=f"{path} asked for {requested} per month but no {doctype} was created.",
				doctype=doctype,
				observed=0,
				expected="> 0",
				remediation="Check the provider warnings for skipped generation.",
			)

	invoices = context.optional(SALES_INVOICES) or []
	if invoices:
		channels = {invoice.get("channel") for invoice in invoices}
		if float(context.section("parties").get("cash_sales_ratio") or 0) > 0 and "cash" not in channels:
			result.warning(
				rule="plausibility.activity_present",
				message="Cash sales were requested but every invoice went through the credit lifecycle.",
				doctype="Sales Invoice",
				expected="at least one counter sale",
			)
	return result
