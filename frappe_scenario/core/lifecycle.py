# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Independent product intent and operational-depth contracts.

Scale controls business volume. Depth controls how far each order proceeds
through its operational and accounting lifecycle. Intent describes why the
dataset exists and does not silently alter either of those choices.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from frappe_scenario.core.errors import SpecificationError

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
		"operations": {"partial_deliveries": 0.02},
	},
	"Everyday Business": {
		"description": "Normal operational coverage with open orders, partial fulfillment, and ageing.",
		"selling": {"delivery_ratio": 0.9, "invoice_ratio": 0.92},
		"buying": {"receipt_ratio": 0.9, "invoice_ratio": 0.9},
		"accounting": {"customer_payment_ratio": 0.75, "supplier_payment_ratio": 0.7},
		"operations": {"partial_deliveries": 0.08},
	},
	"Complex Operations": {
		"description": "Dense lifecycle coverage with more partial fulfillment and outstanding balances.",
		"selling": {"delivery_ratio": 0.95, "invoice_ratio": 0.95},
		"buying": {"receipt_ratio": 0.95, "invoice_ratio": 0.95},
		"accounting": {"customer_payment_ratio": 0.82, "supplier_payment_ratio": 0.78},
		"operations": {"partial_deliveries": 0.18},
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
		"providers": {
			"erpnext.selling": profile["selling"],
			"erpnext.buying": profile["buying"],
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
