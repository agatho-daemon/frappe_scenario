# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""ERPNext selling provider.

Credit customers follow the full lifecycle - Sales Order, Delivery Note, Sales
Invoice - built with ERPNext's own mappers. Cash customers are invoiced directly
with stock updated on the invoice, which is what a counter sale looks like.

Selling rates come from the item's cost-derived rate, with a negotiated discount
that is never allowed to fall below cost unless the specification explicitly
permits it. Quantities are capped by a running availability ledger so the stock
ledger never goes negative.
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
from frappe_scenario.providers.erpnext_parties import CUSTOMERS
from frappe_scenario.providers.support.calendar_tools import (
	as_iso,
	clamp,
	dates_in_month,
	month_starts,
	offset_working_days,
	seasonal_counts,
)
from frappe_scenario.providers.support.pricing import discounted_rate

ORDERS = "erpnext.selling.sales_orders"
DELIVERIES = "erpnext.selling.delivery_notes"
INVOICES = "erpnext.selling.sales_invoices"

SALES_ORDER_MODULE = "erpnext.selling.doctype.sales_order"
DELIVERY_NOTE_MODULE = "erpnext.stock.doctype.delivery_note"

POSTING_TIME = "14:00:00"

#: Largest discount a salesperson may negotiate off the list rate.
MAX_DISCOUNT = 0.08


class ErpnextSellingProvider(ScenarioProvider):
	id = "erpnext.selling"
	version = "0.1.0"
	title = "ERPNext Selling"
	description = "Sales orders, delivery notes, and sales invoices with seasonal demand."
	role = "extender"
	app = "frappe_scenario"
	order = 80

	requires_apps = {"erpnext": ">=15.0.0"}
	requires_capabilities = {COMPANY, ACCOUNTS, ITEMS, WAREHOUSES, CUSTOMERS, PAYMENT_TERMS, STOCK}
	provides_capabilities = {ORDERS, DELIVERIES, INVOICES}

	capabilities = [
		CapabilityDeclaration(
			id=ORDERS,
			description="Submitted sales orders shaped by the archetype's seasonality.",
			doctypes=["Sales Order"],
			requires=[CUSTOMERS, ITEMS],
			validation_rules=["erpnext.selling.order_dates", "erpnext.selling.seasonal_uplift"],
		),
		CapabilityDeclaration(
			id=DELIVERIES,
			description="Delivery notes created from sales orders.",
			doctypes=["Delivery Note"],
			requires=[ORDERS, WAREHOUSES],
			validation_rules=["erpnext.selling.delivery_after_order"],
		),
		CapabilityDeclaration(
			id=INVOICES,
			description="Sales invoices from deliveries, plus direct counter invoices for cash sales.",
			doctypes=["Sales Invoice"],
			requires=[DELIVERIES],
			validation_rules=[
				"erpnext.selling.invoice_margin",
				"erpnext.selling.customer_concentration",
			],
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
				"delivery_ratio": {"type": "number", "minimum": 0, "maximum": 1},
				"invoice_ratio": {"type": "number", "minimum": 0, "maximum": 1},
				"max_discount": {"type": "number", "minimum": 0, "maximum": 0.5},
			},
		}

	# -- planning ------------------------------------------------------------
	def plan(self, context: ScenarioContext) -> ScenarioPlan:
		months = month_starts(context.start_date, context.history_months)
		operations = context.section("operations")
		seasonality = operations.get("seasonality") or {}
		counts = seasonal_counts(
			int(operations.get("sales_orders_per_month") or 0),
			months,
			seasonality.get("peak_months") or [],
			float(seasonality.get("peak_multiplier") or 1.0),
		)
		total = sum(counts)
		options = self.options(context)
		lifecycle = derive_lifecycle_counts(
			sales_activities=total,
			purchase_orders=0,
			depth=context.specification["scenario"]["depth"],
			cash_sales_ratio=float(context.section("parties").get("cash_sales_ratio") or 0),
			overrides={
				"selling": {
					"delivery_ratio": float(options.get("delivery_ratio", 0.9)),
					"invoice_ratio": float(options.get("invoice_ratio", 0.92)),
				}
			},
		)

		plan = ScenarioPlan(provider=self.id)
		plan.step(
			ORDERS,
			f"Create {lifecycle['sales_orders']} credit sales orders across {len(months)} months.",
			doctype="Sales Order",
			count=lifecycle["sales_orders"],
		)
		plan.step(
			DELIVERIES,
			"Deliver the lifecycle-derived share of ordered goods.",
			doctype="Delivery Note",
			count=lifecycle["delivery_notes"],
		)
		plan.step(
			INVOICES,
			"Invoice the lifecycle-derived share of deliveries and counter sales.",
			doctype="Sales Invoice",
			count=lifecycle["sales_invoices"],
		)

		for unsupported in ("returns", "warranty_claims"):
			if float(operations.get(unsupported) or 0) > 0:
				plan.unsupported.append(
					f"operations.{unsupported} is not implemented yet and will be ignored."
				)
		plan.assumptions.append(
			f"Negotiated discounts reach at most {MAX_DISCOUNT:.0%} and never price below cost."
		)
		plan.assumptions.append(
			"Sales quantities are capped by opening stock so the stock ledger never goes negative."
		)
		return plan

	# -- generation ----------------------------------------------------------
	def generate(self, context: ScenarioContext) -> ProviderResult:
		result = ProviderResult(provider=self.id)
		company = context.require(COMPANY)
		options = self.options(context)
		random = context.random("selling")
		pack = context.country_pack
		adapter = context.adapter

		customers = context.require(CUSTOMERS)
		items = context.require(ITEMS)
		warehouses = context.require(WAREHOUSES)
		terms = context.require(PAYMENT_TERMS)
		available = dict((context.optional(STOCK) or {}).get("quantities") or {})

		if not customers or not items:
			context.warning("Selling was skipped: the scenario has no customers or no items.")
			for capability in (ORDERS, DELIVERIES, INVOICES):
				context.publish(capability, [])
			return result

		operations = context.section("operations")
		seasonality = operations.get("seasonality") or {}
		months = month_starts(context.start_date, context.history_months)
		counts = seasonal_counts(
			int(operations.get("sales_orders_per_month") or 0),
			months,
			seasonality.get("peak_months") or [],
			float(seasonality.get("peak_multiplier") or 1.0),
		)

		line_bounds = options.get("lines_per_order") or [1, 4]
		delivery_ratio = float(options.get("delivery_ratio", 0.9))
		invoice_ratio = float(options.get("invoice_ratio", 0.92))
		max_discount = float(options.get("max_discount", MAX_DISCOUNT))

		orders: list[dict[str, Any]] = []
		deliveries: list[dict[str, Any]] = []
		invoices: list[dict[str, Any]] = []
		monthly_orders: dict[str, int] = {}

		for month, count in zip(months, counts, strict=True):
			for order_date in dates_in_month(random, pack, month, count, not_after=context.anchor_date):
				customer = random.choice(customers)
				lines = self._build_lines(random, items, available, line_bounds, pack, max_discount, context)
				if not lines:
					context.warning("Ran out of sellable stock; remaining sales were skipped.")
					continue

				monthly_orders[month.isoformat()[:7]] = monthly_orders.get(month.isoformat()[:7], 0) + 1

				if customer["pays_cash"]:
					invoice = self._create_counter_invoice(
						context,
						company=company,
						customer=customer,
						lines=lines,
						warehouse=warehouses["default"],
						posting_date=order_date,
					)
					invoices.append(invoice)
					continue

				order = self._create_order(
					context,
					company=company,
					customer=customer,
					lines=lines,
					warehouse=warehouses["default"],
					order_date=order_date,
					terms=terms,
					pack=pack,
					random=random,
				)
				orders.append(order)

				if not random.chance(delivery_ratio):
					continue
				delivery = self._create_delivery(
					context, adapter=adapter, order=order, random=random, pack=pack
				)
				if delivery is None:
					continue
				deliveries.append(delivery)

				if not random.chance(invoice_ratio):
					continue
				invoice = self._create_invoice(context, adapter=adapter, delivery=delivery, random=random)
				if invoice is not None:
					invoices.append(invoice)

		context.publish(ORDERS, orders)
		context.publish(DELIVERIES, deliveries)
		context.publish(INVOICES, invoices)
		result.published.extend([ORDERS, DELIVERIES, INVOICES])
		result.summary = {
			"sales_orders": len(orders),
			"delivery_notes": len(deliveries),
			"sales_invoices": len(invoices),
			"orders_by_month": monthly_orders,
		}
		return result

	# -- line building -------------------------------------------------------
	def _build_lines(
		self,
		random: Any,
		items: list[dict[str, Any]],
		available: dict[str, float],
		line_bounds: list[int],
		pack: Any,
		max_discount: float,
		context: ScenarioContext,
	) -> list[dict[str, Any]]:
		"""Pick sellable lines, decrementing the availability ledger as we go."""
		sellable = [
			item for item in items if not item["is_stock_item"] or available.get(item["item_code"], 0) >= 1
		]
		if not sellable:
			return []

		weights = [max(float(item["demand_weight"]), 0.01) for item in sellable]
		wanted = min(random.randint(int(line_bounds[0]), int(line_bounds[1])), len(sellable))

		chosen: list[dict[str, Any]] = []
		seen: set[str] = set()
		for candidate in random.choices(sellable, weights=weights, k=wanted * 3):
			if candidate["item_code"] in seen:
				continue
			seen.add(candidate["item_code"])
			chosen.append(candidate)
			if len(chosen) == wanted:
				break

		lines: list[dict[str, Any]] = []
		for item in chosen:
			low, high = item["quantity_range"]
			quantity = max(1, random.randint(low, high))
			if item["is_stock_item"]:
				quantity = int(min(quantity, available.get(item["item_code"], 0)))
				if quantity < 1:
					continue
				available[item["item_code"]] = available.get(item["item_code"], 0) - quantity

			rate = discounted_rate(random, item["rate"], item["cost"], max_discount, pack.currency_precision)
			lines.append(
				{
					"item_code": item["item_code"],
					"qty": quantity,
					"rate": rate,
					"uom": item["uom"],
					"stock_uom": item["uom"],
					"conversion_factor": 1,
					"__cost": item["cost"],
					"__list_rate": item["rate"],
				}
			)
		return lines

	@staticmethod
	def _document_lines(lines: list[dict[str, Any]], warehouse: str | None) -> list[dict[str, Any]]:
		payload = []
		for line in lines:
			entry = {key: value for key, value in line.items() if not key.startswith("__")}
			if warehouse:
				entry["warehouse"] = warehouse
			payload.append(entry)
		return payload

	# -- sales order ---------------------------------------------------------
	def _create_order(
		self,
		context: ScenarioContext,
		*,
		company: str,
		customer: dict[str, Any],
		lines: list[dict[str, Any]],
		warehouse: str,
		order_date: datetime.date,
		terms: dict[str, str],
		pack: Any,
		random: Any,
	) -> dict[str, Any]:
		context.current_capability = ORDERS
		delivery_date = clamp(
			offset_working_days(pack, order_date, random.randint(2, 12)),
			order_date,
			datetime.date(order_date.year + 5, 12, 31),
		)

		payload = {
			"doctype": "Sales Order",
			"company": company,
			"customer": customer["name"],
			"transaction_date": order_date,
			"delivery_date": delivery_date,
			"currency": context.currency,
			"set_warehouse": warehouse,
			"payment_terms_template": customer.get("payment_terms"),
			"items": self._document_lines(lines, warehouse),
		}
		# ERPNext v16 introduced a transaction clock field whose default is the
		# current time. Set it explicitly so regenerating the same scenario does
		# not depend on wall-clock time; v15 has no such field.
		if context.adapter.has_field("Sales Order", "transaction_time"):
			payload["transaction_time"] = POSTING_TIME

		doc = context.insert(
			payload,
			capability=ORDERS,
			submit=True,
			logical_id=f"sales_order:{order_date.isoformat()}:{customer['name']}",
			dependencies=[f"Customer/{customer['name']}"],
		)

		return {
			"name": doc.name,
			"customer": customer["name"],
			"segment": customer["segment"],
			"credit_days": int(customer.get("credit_days") or 0),
			"order_date": order_date.isoformat(),
			"grand_total": float(doc.grand_total or 0),
			"cost_basis": round(sum(line["__cost"] * line["qty"] for line in lines), 6),
		}

	# -- delivery note -------------------------------------------------------
	def _create_delivery(
		self, context: ScenarioContext, *, adapter: Any, order: dict[str, Any], random: Any, pack: Any
	) -> dict[str, Any] | None:
		context.current_capability = DELIVERIES
		make_delivery_note = adapter.erpnext_mapper(SALES_ORDER_MODULE, "make_delivery_note")

		order_date = datetime.date.fromisoformat(order["order_date"])
		delivery_date = clamp(
			offset_working_days(pack, order_date, random.randint(1, 10)),
			order_date,
			context.anchor_date,
		)

		doc = make_delivery_note(order["name"])
		adapter.set_posting_datetime(doc, delivery_date, POSTING_TIME)

		context.insert_doc(
			doc,
			capability=DELIVERIES,
			submit=True,
			logical_id=f"delivery_note:{order['name']}",
			dependencies=[f"Sales Order/{order['name']}"],
		)

		return {
			"name": doc.name,
			"sales_order": order["name"],
			"customer": order["customer"],
			"credit_days": order["credit_days"],
			"posting_date": delivery_date.isoformat(),
			"grand_total": float(doc.grand_total or 0),
			"cost_basis": order["cost_basis"],
		}

	# -- sales invoice -------------------------------------------------------
	def _create_invoice(
		self, context: ScenarioContext, *, adapter: Any, delivery: dict[str, Any], random: Any
	) -> dict[str, Any] | None:
		context.current_capability = INVOICES
		make_sales_invoice = adapter.erpnext_mapper(DELIVERY_NOTE_MODULE, "make_sales_invoice")

		delivery_date = datetime.date.fromisoformat(delivery["posting_date"])
		invoice_date = clamp(
			delivery_date + datetime.timedelta(days=random.randint(0, 3)),
			delivery_date,
			context.anchor_date,
		)

		doc = make_sales_invoice(delivery["name"])
		adapter.set_posting_datetime(doc, invoice_date, POSTING_TIME)
		# The due date is left to ERPNext, which derives it from the customer's
		# payment terms template and rejects anything later than that.

		context.insert_doc(
			doc,
			capability=INVOICES,
			submit=True,
			logical_id=f"sales_invoice:{delivery['name']}",
			dependencies=[f"Delivery Note/{delivery['name']}"],
		)

		return {
			"name": doc.name,
			"customer": delivery["customer"],
			"delivery_note": delivery["name"],
			"credit_days": delivery["credit_days"],
			"posting_date": invoice_date.isoformat(),
			"due_date": as_iso(doc.due_date),
			"grand_total": float(doc.grand_total or 0),
			"outstanding": float(doc.outstanding_amount or 0),
			"cost_basis": delivery["cost_basis"],
			"channel": "credit",
		}

	def _create_counter_invoice(
		self,
		context: ScenarioContext,
		*,
		company: str,
		customer: dict[str, Any],
		lines: list[dict[str, Any]],
		warehouse: str,
		posting_date: datetime.date,
	) -> dict[str, Any]:
		"""A cash sale: invoiced and delivered in the same document."""
		context.current_capability = INVOICES
		doc = context.insert(
			{
				"doctype": "Sales Invoice",
				"company": company,
				"customer": customer["name"],
				"posting_date": posting_date,
				"posting_time": POSTING_TIME,
				"set_posting_time": 1,
				"due_date": posting_date,
				"currency": context.currency,
				"update_stock": 1,
				"set_warehouse": warehouse,
				"items": self._document_lines(lines, warehouse),
			},
			capability=INVOICES,
			submit=True,
			logical_id=f"sales_invoice_counter:{posting_date.isoformat()}:{customer['name']}",
			dependencies=[f"Customer/{customer['name']}"],
		)

		return {
			"name": doc.name,
			"customer": customer["name"],
			"delivery_note": None,
			"credit_days": 0,
			"posting_date": posting_date.isoformat(),
			"grand_total": float(doc.grand_total or 0),
			"outstanding": float(doc.outstanding_amount or 0),
			"cost_basis": round(sum(line["__cost"] * line["qty"] for line in lines), 6),
			"channel": "cash",
		}

	# -- validation ----------------------------------------------------------
	def validate(self, context: ScenarioContext) -> ValidationResult:
		result = ValidationResult()
		orders = context.optional(ORDERS) or []
		deliveries = context.optional(DELIVERIES) or []
		invoices = context.optional(INVOICES) or []

		for order in orders:
			order_date = datetime.date.fromisoformat(order["order_date"])
			if not (context.start_date <= order_date <= context.anchor_date):
				result.error(
					rule="erpnext.selling.order_dates",
					message=f"Sales Order {order['name']} is dated outside the scenario window.",
					provider=self.id,
					capability=ORDERS,
					doctype="Sales Order",
					record=order["name"],
					observed=order["order_date"],
				)

		for delivery in deliveries:
			order_date = next(
				(order["order_date"] for order in orders if order["name"] == delivery["sales_order"]),
				None,
			)
			if order_date and delivery["posting_date"] < order_date:
				result.error(
					rule="erpnext.selling.delivery_after_order",
					message=f"Delivery Note {delivery['name']} predates its order.",
					provider=self.id,
					capability=DELIVERIES,
					doctype="Delivery Note",
					record=delivery["name"],
					observed=delivery["posting_date"],
					expected=f">= {order_date}",
				)

		self._validate_margins(context, invoices, result)
		self._validate_concentration(context, invoices, result)
		self._validate_seasonality(context, orders, invoices, result)
		return result

	def _validate_margins(
		self, context: ScenarioContext, invoices: list[dict[str, Any]], result: ValidationResult
	) -> None:
		allow_below_cost = bool(context.section("validation").get("allow_below_cost_selling"))
		for invoice in invoices:
			if invoice["cost_basis"] <= 0:
				continue
			if invoice["grand_total"] < invoice["cost_basis"] and not allow_below_cost:
				result.error(
					rule="erpnext.selling.invoice_margin",
					message=(
						f"Sales Invoice {invoice['name']} totals {invoice['grand_total']} against a "
						f"cost basis of {invoice['cost_basis']}."
					),
					provider=self.id,
					capability=INVOICES,
					doctype="Sales Invoice",
					record=invoice["name"],
					observed=invoice["grand_total"],
					expected=f">= {invoice['cost_basis']}",
					remediation="Reduce the negotiated discount or allow below-cost selling.",
				)

	def _validate_concentration(
		self, context: ScenarioContext, invoices: list[dict[str, Any]], result: ValidationResult
	) -> None:
		total = sum(invoice["grand_total"] for invoice in invoices)
		if total <= 0:
			return
		by_customer: dict[str, float] = {}
		for invoice in invoices:
			by_customer[invoice["customer"]] = (
				by_customer.get(invoice["customer"], 0.0) + invoice["grand_total"]
			)

		configured = context.section("validation").get("customer_concentration_threshold")
		if configured is not None:
			threshold = float(configured)
		else:
			# A fixed threshold is meaningless at small scale: with six invoiced
			# customers the average share is already 17%, so any fixed 25% limit
			# reports noise rather than genuine concentration. Flag a customer that
			# takes more than three times an even share instead, with a floor so a
			# large scenario still uses a meaningful absolute limit.
			even_share = 1.0 / max(len(by_customer), 1)
			threshold = max(min(3.0 * even_share, 0.9), 0.25)

		for customer, amount in sorted(by_customer.items()):
			share = amount / total
			if share > threshold:
				result.warning(
					rule="erpnext.selling.customer_concentration",
					message=(
						f"{customer} accounts for {share:.1%} of invoiced revenue across "
						f"{len(by_customer)} invoiced customers."
					),
					provider=self.id,
					capability=INVOICES,
					doctype="Customer",
					record=customer,
					observed=round(share, 4),
					expected=f"<= {threshold:.4f}",
				)

	def _validate_seasonality(
		self,
		context: ScenarioContext,
		orders: list[dict[str, Any]],
		invoices: list[dict[str, Any]],
		result: ValidationResult,
	) -> None:
		seasonality = context.section("operations").get("seasonality") or {}
		peak_months = set(seasonality.get("peak_months") or [])
		multiplier = float(seasonality.get("peak_multiplier") or 1.0)
		if not peak_months or multiplier <= 1.0:
			return

		counts: dict[int, int] = {}
		for record in [*orders, *invoices]:
			key = "order_date" if "order_date" in record else "posting_date"
			month = datetime.date.fromisoformat(record[key]).month
			counts[month] = counts.get(month, 0) + 1

		peak = [count for month, count in counts.items() if month in peak_months]
		off_peak = [count for month, count in counts.items() if month not in peak_months]
		if not peak or not off_peak:
			result.info(
				rule="erpnext.selling.seasonal_uplift",
				message="The history window does not span both peak and off-peak months.",
				provider=self.id,
				capability=ORDERS,
			)
			return

		peak_mean = sum(peak) / len(peak)
		off_peak_mean = sum(off_peak) / len(off_peak)
		if off_peak_mean and peak_mean <= off_peak_mean:
			result.warning(
				rule="erpnext.selling.seasonal_uplift",
				message=(
					f"Peak months average {peak_mean:.1f} transactions against {off_peak_mean:.1f} "
					"off-peak; the expected seasonal uplift is not visible."
				),
				provider=self.id,
				capability=ORDERS,
				observed=round(peak_mean, 2),
				expected=f"> {off_peak_mean:.2f}",
			)
