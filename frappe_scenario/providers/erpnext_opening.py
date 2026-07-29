# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""ERPNext opening provider.

Two opening positions, posted at the start of the scenario window:

* a capital injection, so the company has money before it starts trading;
* opening stock, valued at each item's purchase cost, so early sales have
  inventory to consume and a defensible cost of goods sold.

Both are ordinary submitted documents created through normal controllers, so the
general ledger and stock ledger are produced by ERPNext itself.
"""

from __future__ import annotations

import datetime
from typing import Any

import frappe

from frappe_scenario.core.context import ScenarioContext
from frappe_scenario.core.errors import ProviderError
from frappe_scenario.core.provider import (
	CapabilityDeclaration,
	ProviderResult,
	ScenarioPlan,
	ScenarioProvider,
)
from frappe_scenario.core.validation import ValidationResult
from frappe_scenario.providers.erpnext_catalog import ITEMS, WAREHOUSES
from frappe_scenario.providers.erpnext_foundation import ACCOUNTS, COMPANY

CAPITAL = "erpnext.opening.capital"
STOCK = "erpnext.opening.stock"

POSTING_TIME = "09:00:00"


class ErpnextOpeningProvider(ScenarioProvider):
	id = "erpnext.opening"
	version = "0.1.0"
	title = "ERPNext Opening Balances"
	description = "Opening capital journal entry and opening stock receipt."
	role = "extender"
	app = "frappe_scenario"
	order = 60

	requires_apps = {"erpnext": ">=15.0.0"}
	requires_capabilities = {COMPANY, ACCOUNTS, ITEMS, WAREHOUSES}
	provides_capabilities = {CAPITAL, STOCK}

	capabilities = [
		CapabilityDeclaration(
			id=CAPITAL,
			description="A balanced journal entry funding the company's bank account from equity.",
			doctypes=["Journal Entry"],
			requires=[ACCOUNTS],
			validation_rules=["erpnext.opening.capital_balanced", "erpnext.opening.capital_posted"],
		),
		CapabilityDeclaration(
			id=STOCK,
			description="A material receipt bringing every stock item in at its purchase cost.",
			doctypes=["Stock Entry"],
			requires=[ITEMS, WAREHOUSES],
			validation_rules=["erpnext.opening.stock_valuation"],
		),
	]

	def get_options_schema(self) -> dict[str, Any]:
		return {
			"type": "object",
			"additionalProperties": False,
			"properties": {
				"months_of_cover": {
					"type": "number",
					"minimum": 0.5,
					"maximum": 24,
					"description": "How many months of expected demand opening stock should cover.",
				},
			},
		}

	# -- planning ------------------------------------------------------------
	def plan(self, context: ScenarioContext) -> ScenarioPlan:
		plan = ScenarioPlan(provider=self.id)
		plan.step(CAPITAL, "Post the opening capital journal entry.", doctype="Journal Entry", count=1)
		plan.step(STOCK, "Receive opening stock at purchase cost.", doctype="Stock Entry", count=1)
		if not context.section("accounting").get("opening_capital"):
			plan.assumptions.append(
				"accounting.opening_capital was not supplied; it is derived from the value of "
				"opening stock plus a working capital buffer."
			)
		plan.assumptions.append("Opening entries are posted on the first day of the scenario history window.")
		return plan

	# -- generation ----------------------------------------------------------
	def generate(self, context: ScenarioContext) -> ProviderResult:
		result = ProviderResult(provider=self.id)
		company = context.require(COMPANY)
		accounts = context.require(ACCOUNTS)

		stock = self._receive_opening_stock(context, company, accounts)
		context.publish(STOCK, stock)
		result.published.append(STOCK)

		capital = self._post_opening_capital(context, company, accounts, stock["value"])
		context.publish(CAPITAL, capital)
		result.published.append(CAPITAL)

		result.summary = {"opening_stock_value": stock["value"], "opening_capital": capital["amount"]}
		return result

	# -- opening stock -------------------------------------------------------
	def _receive_opening_stock(
		self, context: ScenarioContext, company: str, accounts: dict[str, Any]
	) -> dict[str, Any]:
		context.current_capability = STOCK
		random = context.random("opening_stock")
		warehouses = context.require(WAREHOUSES)
		items = context.require(ITEMS)
		precision = int(accounts.get("currency_precision") or 2)
		cover = float(self.options(context).get("months_of_cover") or 3.0)

		posting_date = context.start_date
		lines: list[dict[str, Any]] = []
		quantities: dict[str, float] = {}
		value = 0.0

		for item in items:
			if not item["is_stock_item"]:
				continue
			low, high = item["quantity_range"]
			quantity = max(1, round(random.randint(low, high) * cover))
			quantities[item["item_code"]] = quantity
			value += round(quantity * item["cost"], precision)
			lines.append(
				{
					"item_code": item["item_code"],
					"qty": quantity,
					"uom": item["uom"],
					"stock_uom": item["uom"],
					"conversion_factor": 1,
					"basic_rate": item["cost"],
					"t_warehouse": warehouses["default"],
					"allow_zero_valuation_rate": 0,
				}
			)

		if not lines:
			context.warning("The catalog has no stock items; opening stock was skipped.")
			return {"stock_entry": None, "value": 0.0, "quantities": {}, "warehouse": warehouses["default"]}

		doc = context.insert(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"purpose": "Material Receipt",
				"company": company,
				"posting_date": posting_date,
				"posting_time": POSTING_TIME,
				"set_posting_time": 1,
				"to_warehouse": warehouses["default"],
				"items": lines,
				"remarks": "Opening stock generated by frappe_scenario.",
			},
			capability=STOCK,
			submit=True,
			logical_id="opening_stock",
		)
		context.progress(f"Received opening stock in {len(lines)} lines.")

		return {
			"stock_entry": doc.name,
			"value": round(value, precision),
			"quantities": quantities,
			"warehouse": warehouses["default"],
			"posting_date": posting_date.isoformat(),
		}

	# -- opening capital -----------------------------------------------------
	def _post_opening_capital(
		self,
		context: ScenarioContext,
		company: str,
		accounts: dict[str, Any],
		stock_value: float,
	) -> dict[str, Any]:
		context.current_capability = CAPITAL
		precision = int(accounts.get("currency_precision") or 2)
		configured = context.section("accounting").get("opening_capital")

		# Enough to have paid for opening stock and still fund early operations.
		amount = float(configured) if configured else round(max(stock_value, 1000.0) * 2.0, precision)

		bank = accounts.get("bank")
		equity = accounts.get("equity")
		if not bank or not equity:
			raise ProviderError(
				"Opening capital needs a bank account and an equity account.",
				provider=self.id,
				capability=CAPITAL,
				phase="generate",
				details={"bank": bank, "equity": equity},
			)

		doc = context.insert(
			{
				"doctype": "Journal Entry",
				"voucher_type": "Journal Entry",
				"company": company,
				"posting_date": context.start_date,
				"user_remark": "Opening capital contributed by the owners.",
				"accounts": [
					{
						"account": bank,
						"debit_in_account_currency": amount,
						"cost_center": accounts.get("cost_center"),
					},
					{
						"account": equity,
						"credit_in_account_currency": amount,
						"cost_center": accounts.get("cost_center"),
					},
				],
			},
			capability=CAPITAL,
			submit=True,
			logical_id="opening_capital",
		)
		context.progress(f"Posted opening capital of {amount}.")
		return {"journal_entry": doc.name, "amount": amount, "bank": bank, "equity": equity}

	# -- validation ----------------------------------------------------------
	def validate(self, context: ScenarioContext) -> ValidationResult:
		result = ValidationResult()
		capital = context.optional(CAPITAL) or {}
		stock = context.optional(STOCK) or {}

		entry = capital.get("journal_entry")
		if not entry:
			result.error(
				rule="erpnext.opening.capital_posted",
				message="No opening capital journal entry was created.",
				provider=self.id,
				capability=CAPITAL,
			)
		else:
			doc = frappe.get_doc("Journal Entry", entry)
			if doc.docstatus != 1:
				result.error(
					rule="erpnext.opening.capital_posted",
					message=f"Journal Entry {entry} is not submitted.",
					provider=self.id,
					capability=CAPITAL,
					doctype="Journal Entry",
					record=entry,
					observed=doc.docstatus,
					expected=1,
				)
			if round(doc.total_debit - doc.total_credit, 4) != 0:
				result.error(
					rule="erpnext.opening.capital_balanced",
					message=f"Journal Entry {entry} does not balance.",
					provider=self.id,
					capability=CAPITAL,
					doctype="Journal Entry",
					record=entry,
					observed=[doc.total_debit, doc.total_credit],
				)

		if stock.get("stock_entry"):
			posted = frappe.db.get_value("Stock Entry", stock["stock_entry"], "docstatus")
			if posted != 1:
				result.error(
					rule="erpnext.opening.stock_valuation",
					message=f"Opening Stock Entry {stock['stock_entry']} is not submitted.",
					provider=self.id,
					capability=STOCK,
					doctype="Stock Entry",
					record=stock["stock_entry"],
				)
		return result


def _as_date(value: Any) -> datetime.date:
	if isinstance(value, datetime.date):
		return value
	return datetime.date.fromisoformat(str(value)[:10])
