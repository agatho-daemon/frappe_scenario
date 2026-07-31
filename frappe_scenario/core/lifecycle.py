# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Independent product intent and operational-depth contracts.

Scale controls business volume. Depth controls how far each order proceeds
through its operational and accounting lifecycle. Intent describes why the
dataset exists and does not silently alter either of those choices.
"""

from __future__ import annotations

import datetime
from copy import deepcopy
from typing import Any

from frappe_scenario.core.errors import SpecificationError
from frappe_scenario.providers.support.calendar_tools import month_starts, seasonal_counts

PRODUCT_INTENTS = (
	"Learn ERPNext",
	"Quick Demo",
	"Presentation Demo",
	"Realistic Business",
	"Custom/AI Brief",
	"Developer/Test Dataset",
)

OPERATIONAL_DEPTHS = ("Essentials", "Everyday Business", "Complex Operations")

DEPTH_PROFILES: dict[str, dict[str, Any]] = {
	"Essentials": {
		"description": "Core order, fulfillment, invoice, and payment examples with few exceptions.",
		"selling": {"delivery_ratio": 0.8, "invoice_ratio": 0.85},
		"buying": {"receipt_ratio": 0.8, "invoice_ratio": 0.85},
		"accounting": {"customer_payment_ratio": 0.65, "supplier_payment_ratio": 0.65},
		"operations": {
			"partial_deliveries": 0.02,
			"opportunity_ratio": 0.15,
			"quotation_ratio": 0.6,
			"stock_transfers": 1,
		},
		"accounting_controls": {"bank_reconciliation_ratio": 0.5, "period_closing": True},
	},
	"Everyday Business": {
		"description": "Normal operational coverage with open orders, partial fulfillment, and ageing.",
		"selling": {"delivery_ratio": 0.9, "invoice_ratio": 0.92},
		"buying": {"receipt_ratio": 0.9, "invoice_ratio": 0.9},
		"accounting": {"customer_payment_ratio": 0.75, "supplier_payment_ratio": 0.7},
		"operations": {
			"partial_deliveries": 0.08,
			"opportunity_ratio": 0.25,
			"quotation_ratio": 0.7,
			"stock_transfers": 1,
		},
		"accounting_controls": {"bank_reconciliation_ratio": 0.65, "period_closing": True},
	},
	"Complex Operations": {
		"description": "Dense lifecycle coverage with more partial fulfillment and outstanding balances.",
		"selling": {"delivery_ratio": 0.95, "invoice_ratio": 0.95},
		"buying": {"receipt_ratio": 0.95, "invoice_ratio": 0.95},
		"accounting": {"customer_payment_ratio": 0.82, "supplier_payment_ratio": 0.78},
		"operations": {
			"partial_deliveries": 0.18,
			"opportunity_ratio": 0.4,
			"quotation_ratio": 0.8,
			"stock_transfers": 2,
		},
		"accounting_controls": {"bank_reconciliation_ratio": 0.8, "period_closing": True},
	},
}


def get_depth_profile(depth: str) -> dict[str, Any]:
	profile = DEPTH_PROFILES.get(depth)
	if profile is None:
		raise SpecificationError(
			f"Unknown operational depth {depth!r}.",
			phase="plan",
			details={"depth": depth, "known": list(OPERATIONAL_DEPTHS)},
		)
	return deepcopy(profile)


def depth_specification_defaults(depth: str) -> dict[str, Any]:
	"""Translate a depth into existing provider and specification controls."""
	profile = get_depth_profile(depth)
	return {
		"operations": profile["operations"],
		"accounting": profile["accounting"],
		"accounting_controls": profile["accounting_controls"],
		"providers": {
			"erpnext.commercial": {},
			"erpnext.selling": profile["selling"],
			"erpnext.buying": profile["buying"],
			"erpnext.payments": {},
		},
	}


def derive_lifecycle_counts(
	*,
	sales_activities: int,
	purchase_orders: int,
	depth: str,
	cash_sales_ratio: float = 0,
	overrides: dict[str, Any] | None = None,
) -> dict[str, int]:
	"""Derive downstream document counts from activity and lifecycle ratios."""
	profile = get_depth_profile(depth)
	overrides = overrides or {}
	selling = {**profile["selling"], **(overrides.get("selling") or {})}
	buying = {**profile["buying"], **(overrides.get("buying") or {})}
	accounting = {**profile["accounting"], **(overrides.get("accounting") or {})}

	cash_sales = round(sales_activities * cash_sales_ratio)
	sales_orders = max(sales_activities - cash_sales, 0)
	deliveries = round(sales_orders * float(selling["delivery_ratio"]))
	sales_invoices = cash_sales + round(deliveries * float(selling["invoice_ratio"]))
	purchase_receipts = round(purchase_orders * float(buying["receipt_ratio"]))
	purchase_invoices = round(purchase_receipts * float(buying["invoice_ratio"]))
	return {
		"sales_activities": sales_activities,
		"sales_orders": sales_orders,
		"cash_sales_invoices": cash_sales,
		"delivery_notes": deliveries,
		"sales_invoices": sales_invoices,
		"customer_payments": round(sales_invoices * float(accounting["customer_payment_ratio"])),
		"purchase_orders": purchase_orders,
		"purchase_receipts": purchase_receipts,
		"purchase_invoices": purchase_invoices,
		"supplier_payments": round(purchase_invoices * float(accounting["supplier_payment_ratio"])),
	}


def forecast_specification_lifecycle(specification: dict[str, Any]) -> dict[str, int]:
	"""Forecast provider document counts from one resolved business specification."""
	scenario = specification["scenario"]
	operations = specification.get("operations") or {}
	seasonality = operations.get("seasonality") or {}
	anchor = datetime.date.fromisoformat(scenario["anchor_date"])
	months_count = int(scenario["history_months"])
	year, month = anchor.year, anchor.month - months_count
	while month <= 0:
		month += 12
		year -= 1
	months = month_starts(datetime.date(year, month, 1), months_count)
	peak_months = seasonality.get("peak_months") or []
	peak_multiplier = float(seasonality.get("peak_multiplier") or 1)
	sales = sum(
		seasonal_counts(
			int(operations.get("sales_orders_per_month") or 0), months, peak_months, peak_multiplier
		)
	)
	purchases = sum(
		seasonal_counts(
			int(operations.get("purchase_orders_per_month") or 0),
			months,
			peak_months,
			peak_multiplier,
		)
	)
	providers = specification.get("providers") or {}
	return derive_lifecycle_counts(
		sales_activities=sales,
		purchase_orders=purchases,
		depth=scenario["depth"],
		cash_sales_ratio=float((specification.get("parties") or {}).get("cash_sales_ratio") or 0),
		overrides={
			"selling": providers.get("erpnext.selling") or {},
			"buying": providers.get("erpnext.buying") or {},
			"accounting": specification.get("accounting") or {},
		},
	)
