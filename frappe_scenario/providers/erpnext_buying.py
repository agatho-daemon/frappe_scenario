# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""ERPNext buying provider.

A complete purchase lifecycle: Purchase Order, Purchase Receipt, Purchase
Invoice. Downstream documents are produced with ERPNext's own mappers, resolved
through the compatibility adapter because develop moved them into per-DocType
``mapper`` modules.

Purchase cost is the price foundation for the whole scenario, so order rates come
from the item's recorded cost with only a small negotiated variance.
"""

from __future__ import annotations

import datetime
from typing import Any

import frappe

from frappe_scenario.core.context import ScenarioContext
from frappe_scenario.core.lifecycle import derive_lifecycle_counts
from frappe_scenario.core.provider import (
	CapabilityDeclaration,
	ProviderResult,
	ScenarioPlan,
	ScenarioProvider,
)
from frappe_scenario.core.validation import ValidationResult
from frappe_scenario.providers.erpnext_catalog import ITEMS, WAREHOUSES
from frappe_scenario.providers.erpnext_foundation import ACCOUNTS, COMPANY, PAYMENT_TERMS
from frappe_scenario.providers.erpnext_opening import STOCK
from frappe_scenario.providers.erpnext_parties import SUPPLIERS
from frappe_scenario.providers.support.calendar_tools import (
	as_iso,
	clamp,
	dates_in_month,
	month_starts,
	offset_working_days,
	seasonal_counts,
)

ORDERS = "erpnext.buying.purchase_orders"
RECEIPTS = "erpnext.buying.purchase_receipts"
INVOICES = "erpnext.buying.purchase_invoices"

PURCHASE_ORDER_MODULE = "erpnext.buying.doctype.purchase_order"
PURCHASE_RECEIPT_MODULE = "erpnext.stock.doctype.purchase_receipt"

POSTING_TIME = "11:00:00"

#: Suppliers rarely quote exactly the recorded cost; this is the negotiated band.
COST_VARIANCE = 0.05


class ErpnextBuyingProvider(ScenarioProvider):
	id = "erpnext.buying"
	version = "0.2.0"
	title = "ERPNext Buying"
	description = "Purchase orders, receipts, and invoices linked through ERPNext's own mappers."
	role = "extender"
	app = "frappe_scenario"
	order = 70

	requires_apps = {"erpnext": ">=15.0.0"}
	requires_capabilities = {COMPANY, ACCOUNTS, ITEMS, WAREHOUSES, SUPPLIERS, PAYMENT_TERMS}
	optional_capabilities = {STOCK}
	provides_capabilities = {ORDERS, RECEIPTS, INVOICES}

	capabilities = [
		CapabilityDeclaration(
			id=ORDERS,
			description="Submitted purchase orders spread across the history window.",
			doctypes=["Purchase Order"],
			requires=[SUPPLIERS, ITEMS],
			validation_rules=["erpnext.buying.order_dates", "erpnext.buying.order_rates"],
		),
		CapabilityDeclaration(
			id=RECEIPTS,
			description="Purchase receipts created from orders, honouring supplier lead times.",
			doctypes=["Purchase Receipt"],
			requires=[ORDERS, WAREHOUSES],
			validation_rules=["erpnext.buying.receipt_after_order"],
		),
		CapabilityDeclaration(
			id=INVOICES,
			description="Purchase invoices created from receipts.",
			doctypes=["Purchase Invoice"],
			requires=[RECEIPTS],
			validation_rules=["erpnext.buying.invoice_linked"],
		),
	]

	def get_options_schema(self) -> dict[str, Any]:
		return {
			"type": "object",
			"additionalProperties": False,
			"properties": {
				"lines_per_order": {
					"type": "array",
					"minItems": 2,
					"maxItems": 2,
					"items": {"type": "integer"},
				},
				"receipt_ratio": {"type": "number", "minimum": 0, "maximum": 1},
				"invoice_ratio": {"type": "number", "minimum": 0, "maximum": 1},
			},
		}

	# -- planning ------------------------------------------------------------
	def plan(self, context: ScenarioContext) -> ScenarioPlan:
		months = month_starts(context.start_date, context.history_months)
		operations = context.section("operations")
		counts = seasonal_counts(
			int(operations.get("purchase_orders_per_month") or 0),
			months,
			(operations.get("seasonality") or {}).get("peak_months") or [],
			float((operations.get("seasonality") or {}).get("peak_multiplier") or 1.0),
		)
		total = sum(counts)
		options = self.options(context)
		lifecycle = derive_lifecycle_counts(
			sales_activities=0,
			purchase_orders=total,
			depth=context.specification["scenario"]["depth"],
			overrides={
				"buying": {
					"receipt_ratio": float(options.get("receipt_ratio", 0.9)),
					"invoice_ratio": float(options.get("invoice_ratio", 0.9)),
				}
			},
		)

		plan = ScenarioPlan(provider=self.id)
		plan.step(
			ORDERS,
			f"Create {total} purchase orders across {len(months)} months.",
			doctype="Purchase Order",
			count=total,
		)
		plan.step(
			RECEIPTS,
			"Receive ordered goods after the supplier lead time.",
			doctype="Purchase Receipt",
			count=lifecycle["purchase_receipts"],
		)
		plan.step(
			INVOICES,
			"Invoice the lifecycle-derived share of receipts.",
			doctype="Purchase Invoice",
			count=lifecycle["purchase_invoices"],
		)
		plan.assumptions.append(f"Order rates vary within {COST_VARIANCE:.0%} of the recorded item cost.")
		plan.cleanup_notes.append(
			"Cleanup cancels invoices, then receipts, then orders, before deleting them."
		)
		return plan

	# -- generation ----------------------------------------------------------
	def generate(self, context: ScenarioContext) -> ProviderResult:
		result = ProviderResult(provider=self.id)
		company = context.require(COMPANY)
		options = self.options(context)
		random = context.random("buying")
		pack = context.country_pack
		adapter = context.adapter

		suppliers = context.require(SUPPLIERS)
		items = [item for item in context.require(ITEMS) if item["is_stock_item"]]
		warehouses = context.require(WAREHOUSES)
		terms = context.require(PAYMENT_TERMS)

		if not suppliers or not items:
			context.warning("Buying was skipped: the scenario has no suppliers or no stock items.")
			for capability in (ORDERS, RECEIPTS, INVOICES):
				context.publish(capability, [])
			return result

		operations = context.section("operations")
		seasonality = operations.get("seasonality") or {}
		months = month_starts(context.start_date, context.history_months)
		counts = seasonal_counts(
			int(operations.get("purchase_orders_per_month") or 0),
			months,
			seasonality.get("peak_months") or [],
			float(seasonality.get("peak_multiplier") or 1.0),
		)

		line_bounds = options.get("lines_per_order") or [1, 4]
		receipt_ratio = float(options.get("receipt_ratio", 0.9))
		invoice_ratio = float(options.get("invoice_ratio", 0.9))
		partial_ratio = float(operations.get("partial_deliveries") or 0.0)

		orders: list[dict[str, Any]] = []
		receipts: list[dict[str, Any]] = []
		invoices: list[dict[str, Any]] = []

		context.current_capability = ORDERS
		for month, count in zip(months, counts, strict=True):
			for order_date in dates_in_month(random, pack, month, count, not_after=context.anchor_date):
				supplier = random.choices(
					suppliers,
					weights=_activity_weights(
						len(suppliers), float(operations.get("supplier_concentration") or 0)
					),
					k=1,
				)[0]
				order = self._create_order(
					context,
					company=company,
					supplier=supplier,
					items=items,
					warehouse=warehouses["default"],
					order_date=order_date,
					line_bounds=line_bounds,
					terms=terms,
					random=random,
					pack=pack,
				)
				orders.append(order)

				if not random.chance(receipt_ratio):
					continue
				receipt = self._create_receipt(
					context,
					adapter=adapter,
					order=order,
					random=random,
					pack=pack,
					partial_ratio=partial_ratio,
				)
				if receipt is None:
					continue
				receipts.append(receipt)

				if not random.chance(invoice_ratio):
					continue
				invoice = self._create_invoice(context, adapter=adapter, receipt=receipt, random=random)
				if invoice is not None:
					invoices.append(invoice)

		context.publish(ORDERS, orders)
		context.publish(RECEIPTS, receipts)
		context.publish(INVOICES, invoices)
		result.published.extend([ORDERS, RECEIPTS, INVOICES])
		result.summary = {
			"purchase_orders": len(orders),
			"purchase_receipts": len(receipts),
			"purchase_invoices": len(invoices),
		}
		return result

	# -- purchase order ------------------------------------------------------
	def _create_order(
		self,
		context: ScenarioContext,
		*,
		company: str,
		supplier: dict[str, Any],
		items: list[dict[str, Any]],
		warehouse: str,
		order_date: datetime.date,
		line_bounds: list[int],
		terms: dict[str, str],
		random: Any,
		pack: Any,
	) -> dict[str, Any]:
		context.current_capability = ORDERS
		line_count = min(random.randint(int(line_bounds[0]), int(line_bounds[1])), len(items))
		chosen = random.sample(items, line_count)

		lead_days = 0
		lines: list[dict[str, Any]] = []
		for item in chosen:
			low, high = item["quantity_range"]
			quantity = max(1, random.randint(low, high))
			rate = round(
				item["cost"] * (1 + random.uniform(-COST_VARIANCE, COST_VARIANCE)),
				pack.currency_precision,
			)
			item_lead = random.randint(*item["lead_time_days"]) if item["lead_time_days"][1] else 0
			lead_days = max(lead_days, item_lead + int(supplier.get("lead_time_bias") or 0))
			lines.append(
				{
					"item_code": item["item_code"],
					"qty": quantity,
					"rate": max(rate, 0.001),
					"uom": item["uom"],
					"stock_uom": item["uom"],
					"conversion_factor": 1,
					"warehouse": warehouse,
					"schedule_date": offset_working_days(pack, order_date, max(item_lead, 1)),
				}
			)

		schedule_date = clamp(
			offset_working_days(pack, order_date, max(lead_days, 1)),
			order_date,
			datetime.date(order_date.year + 5, 12, 31),
		)

		payload = {
			"doctype": "Purchase Order",
			"company": company,
			"supplier": supplier["name"],
			"transaction_date": order_date,
			"schedule_date": schedule_date,
			"currency": context.currency,
			"set_warehouse": warehouse,
			"payment_terms_template": terms.get(supplier.get("term_key") or "cash"),
			"items": lines,
		}
		# ERPNext v16 introduced a transaction clock field whose default is the
		# current time. Keep it seeded by the scenario rather than the wall clock.
		if context.adapter.has_field("Purchase Order", "transaction_time"):
			payload["transaction_time"] = POSTING_TIME

		doc = context.insert(
			payload,
			capability=ORDERS,
			submit=True,
			logical_id=f"purchase_order:{order_date.isoformat()}:{supplier['name']}",
			dependencies=[f"Supplier/{supplier['name']}"],
		)

		return {
			"name": doc.name,
			"supplier": supplier["name"],
			"term_key": supplier.get("term_key") or "cash",
			"credit_days": int(supplier.get("credit_days") or 0),
			"order_date": order_date.isoformat(),
			"lead_days": max(lead_days, 1),
			"grand_total": float(doc.grand_total or 0),
		}

	# -- purchase receipt ----------------------------------------------------
	def _create_receipt(
		self,
		context: ScenarioContext,
		*,
		adapter: Any,
		order: dict[str, Any],
		random: Any,
		pack: Any,
		partial_ratio: float,
	) -> dict[str, Any] | None:
		context.current_capability = RECEIPTS
		make_purchase_receipt = adapter.erpnext_mapper(PURCHASE_ORDER_MODULE, "make_purchase_receipt")

		order_date = datetime.date.fromisoformat(order["order_date"])
		receipt_date = clamp(
			offset_working_days(pack, order_date, order["lead_days"]),
			order_date,
			context.anchor_date,
		)
		if receipt_date < order_date:
			return None

		doc = make_purchase_receipt(order["name"])
		adapter.set_posting_datetime(doc, receipt_date, POSTING_TIME)

		partial = random.chance(partial_ratio)
		if partial:
			for line in doc.items:
				if line.qty > 1:
					line.qty = max(1, int(line.qty * random.uniform(0.4, 0.8)))
					line.received_qty = line.qty

		context.insert_doc(
			doc,
			capability=RECEIPTS,
			submit=True,
			logical_id=f"purchase_receipt:{order['name']}",
			dependencies=[f"Purchase Order/{order['name']}"],
		)

		return {
			"name": doc.name,
			"purchase_order": order["name"],
			"supplier": order["supplier"],
			"term_key": order["term_key"],
			"credit_days": order["credit_days"],
			"posting_date": receipt_date.isoformat(),
			"partial": partial,
			"grand_total": float(doc.grand_total or 0),
		}

	# -- purchase invoice ----------------------------------------------------
	def _create_invoice(
		self, context: ScenarioContext, *, adapter: Any, receipt: dict[str, Any], random: Any
	) -> dict[str, Any] | None:
		context.current_capability = INVOICES
		make_purchase_invoice = adapter.erpnext_mapper(PURCHASE_RECEIPT_MODULE, "make_purchase_invoice")

		receipt_date = datetime.date.fromisoformat(receipt["posting_date"])
		invoice_date = clamp(
			receipt_date + datetime.timedelta(days=random.randint(0, 5)),
			receipt_date,
			context.anchor_date,
		)

		doc = make_purchase_invoice(receipt["name"])
		adapter.set_posting_datetime(doc, invoice_date, POSTING_TIME)
		doc.bill_no = f"INV-{receipt['name']}"
		doc.bill_date = invoice_date
		# The due date is left to ERPNext. The supplier carries a payment terms
		# template, and ERPNext rejects any due date later than the one that
		# template implies, so recomputing it here could only drift out of range.

		context.insert_doc(
			doc,
			capability=INVOICES,
			submit=True,
			logical_id=f"purchase_invoice:{receipt['name']}",
			dependencies=[f"Purchase Receipt/{receipt['name']}"],
		)

		return {
			"name": doc.name,
			"supplier": receipt["supplier"],
			"purchase_receipt": receipt["name"],
			"term_key": receipt["term_key"],
			"credit_days": receipt["credit_days"],
			"posting_date": invoice_date.isoformat(),
			"due_date": as_iso(doc.due_date),
			"grand_total": float(doc.grand_total or 0),
			"outstanding": float(doc.outstanding_amount or 0),
		}

	# -- validation ----------------------------------------------------------
	def validate(self, context: ScenarioContext) -> ValidationResult:
		result = ValidationResult()
		orders = context.optional(ORDERS) or []
		receipts = context.optional(RECEIPTS) or []
		invoices = context.optional(INVOICES) or []

		for order in orders:
			order_date = datetime.date.fromisoformat(order["order_date"])
			if not (context.start_date <= order_date <= context.anchor_date):
				result.error(
					rule="erpnext.buying.order_dates",
					message=f"Purchase Order {order['name']} is dated outside the scenario window.",
					provider=self.id,
					capability=ORDERS,
					doctype="Purchase Order",
					record=order["name"],
					observed=order["order_date"],
					expected=f"{context.start_date} .. {context.anchor_date}",
				)
			if order["grand_total"] <= 0:
				result.error(
					rule="erpnext.buying.order_rates",
					message=f"Purchase Order {order['name']} has a non-positive total.",
					provider=self.id,
					capability=ORDERS,
					doctype="Purchase Order",
					record=order["name"],
					observed=order["grand_total"],
				)

		for receipt in receipts:
			order_date = next(
				(order["order_date"] for order in orders if order["name"] == receipt["purchase_order"]),
				None,
			)
			if order_date and receipt["posting_date"] < order_date:
				result.error(
					rule="erpnext.buying.receipt_after_order",
					message=f"Purchase Receipt {receipt['name']} predates its order.",
					provider=self.id,
					capability=RECEIPTS,
					doctype="Purchase Receipt",
					record=receipt["name"],
					observed=receipt["posting_date"],
					expected=f">= {order_date}",
				)

		for invoice in invoices:
			linked = frappe.db.exists(
				"Purchase Invoice Item",
				{"parent": invoice["name"], "purchase_receipt": invoice["purchase_receipt"]},
			)
			if not linked:
				result.error(
					rule="erpnext.buying.invoice_linked",
					message=(
						f"Purchase Invoice {invoice['name']} is not linked to receipt "
						f"{invoice['purchase_receipt']}."
					),
					provider=self.id,
					capability=INVOICES,
					doctype="Purchase Invoice",
					record=invoice["name"],
				)
		return result


def _activity_weights(count: int, concentration: float) -> list[float]:
	if count <= 1:
		return [1.0] * count
	concentration = min(max(concentration, 0.0), 1.0)
	return [1.0 + concentration * 4.0 * (1.0 - index / (count - 1)) for index in range(count)]
