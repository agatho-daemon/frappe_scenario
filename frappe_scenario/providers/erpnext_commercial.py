# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Commercial controls before the buying and selling transaction streams."""

from __future__ import annotations

import datetime
from typing import Any

import frappe

from frappe_scenario.core.context import ScenarioContext
from frappe_scenario.core.lifecycle import forecast_specification_lifecycle
from frappe_scenario.core.provider import (
	CapabilityDeclaration,
	ProviderResult,
	ScenarioPlan,
	ScenarioProvider,
)
from frappe_scenario.core.validation import ValidationResult
from frappe_scenario.providers.erpnext_catalog import ITEMS, WAREHOUSES
from frappe_scenario.providers.erpnext_foundation import ACCOUNTS, COMPANY
from frappe_scenario.providers.erpnext_opening import STOCK
from frappe_scenario.providers.erpnext_parties import CUSTOMERS
from frappe_scenario.providers.support import erpnext_tools as tools
from frappe_scenario.providers.support.calendar_tools import clamp

CRM = "erpnext.commercial.crm"
TAXES = "erpnext.commercial.taxes"
CREDIT_LIMITS = "erpnext.commercial.credit_limits"
TRANSFERS = "erpnext.commercial.stock_transfers"


class ErpnextCommercialProvider(ScenarioProvider):
	id = "erpnext.commercial"
	version = "0.1.0"
	title = "ERPNext Commercial Controls"
	description = "CRM, taxes, credit policy, and inter-warehouse stock movement."
	role = "extender"
	app = "frappe_scenario"
	order = 65

	requires_apps = {"erpnext": ">=15.0.0"}
	requires_capabilities = {COMPANY, ACCOUNTS, CUSTOMERS, ITEMS, WAREHOUSES, STOCK}
	provides_capabilities = {CRM, TAXES, CREDIT_LIMITS, TRANSFERS}

	capabilities = [
		CapabilityDeclaration(
			id=CRM,
			description="Customer opportunities followed by submitted quotations.",
			doctypes=["Opportunity", "Quotation"],
			requires=[CUSTOMERS, ITEMS],
			validation_rules=["erpnext.commercial.crm_links"],
		),
		CapabilityDeclaration(
			id=TAXES,
			description="Optional explicitly configured sales and purchase tax templates.",
			doctypes=["Account", "Sales Taxes and Charges Template", "Purchase Taxes and Charges Template"],
			requires=[COMPANY, ACCOUNTS],
			validation_rules=["erpnext.commercial.tax_templates"],
		),
		CapabilityDeclaration(
			id=CREDIT_LIMITS,
			description="Company-specific customer credit limits derived from monthly activity.",
			doctypes=["Customer"],
			requires=[CUSTOMERS],
			validation_rules=["erpnext.commercial.credit_limits"],
		),
		CapabilityDeclaration(
			id=TRANSFERS,
			description="Submitted material transfers between scenario warehouses.",
			doctypes=["Stock Entry"],
			requires=[WAREHOUSES, STOCK],
			validation_rules=["erpnext.commercial.stock_transfers"],
		),
	]

	def plan(self, context: ScenarioContext) -> ScenarioPlan:
		operations = context.section("operations")
		lifecycle = forecast_specification_lifecycle(context.specification)
		opportunities = round(lifecycle["sales_activities"] * float(operations.get("opportunity_ratio") or 0))
		quotations = round(opportunities * float(operations.get("quotation_ratio") or 0))
		transfers = int(operations.get("stock_transfers") or 0)
		tax_rate = float(context.section("accounting_controls").get("indirect_tax_rate") or 0)
		plan = ScenarioPlan(provider=self.id)
		plan.step(
			CRM,
			"Create opportunity-to-quotation CRM stories.",
			doctype="Opportunity",
			count=opportunities + quotations,
		)
		plan.step(
			TAXES,
			"Create explicit non-regulatory tax templates when a rate is configured.",
			doctype="Sales Taxes and Charges Template",
			count=5 if tax_rate else 0,
		)
		plan.step(
			CREDIT_LIMITS,
			"Assign company credit limits to account customers.",
			doctype="Customer",
			count=int(context.section("parties").get("customers") or 0),
		)
		plan.step(
			TRANSFERS,
			"Move controlled stock quantities between scenario warehouses.",
			doctype="Stock Entry",
			count=transfers,
		)
		if not tax_rate:
			plan.assumptions.append(
				"No indirect tax rate was asserted for this country; tax templates are omitted rather than inventing regulation."
			)
		plan.assumptions.append(
			"Credit limits are high enough for normal generated trade but still produce useful exposure reports."
		)
		return plan

	def generate(self, context: ScenarioContext) -> ProviderResult:
		result = ProviderResult(provider=self.id)
		taxes = self._create_tax_templates(context)
		context.publish(TAXES, taxes)
		limits = self._apply_credit_limits(context)
		context.publish(CREDIT_LIMITS, limits)
		crm = self._create_crm(context, taxes)
		context.publish(CRM, crm)
		transfers = self._create_transfers(context)
		context.publish(TRANSFERS, transfers)
		result.published.extend([TAXES, CREDIT_LIMITS, CRM, TRANSFERS])
		result.summary = {
			"opportunities": len(crm["opportunities"]),
			"quotations": len(crm["quotations"]),
			"credit_limits": len(limits),
			"stock_transfers": len(transfers),
			"tax_rate": taxes.get("rate", 0),
		}
		return result

	def _create_tax_templates(self, context: ScenarioContext) -> dict[str, Any]:
		context.current_capability = TAXES
		rate = float(context.section("accounting_controls").get("indirect_tax_rate") or 0)
		if rate <= 0:
			return {"rate": 0, "sales_template": None, "purchase_template": None}
		company = context.require(COMPANY)
		abbr = tools.company_abbr(company)
		liability_group = tools.account_group(company, account_name="Duties and Taxes", root_type="Liability")
		if not liability_group:
			context.warning("Tax templates were skipped because the chart has no Duties and Taxes group.")
			return {"rate": 0, "sales_template": None, "purchase_template": None}
		account = context.insert(
			{
				"doctype": "Account",
				"account_name": f"Scenario Indirect Tax {rate:g}%",
				"parent_account": liability_group,
				"company": company,
				"root_type": "Liability",
				"account_type": "Tax",
				"is_group": 0,
			},
			capability=TAXES,
			logical_id="indirect_tax_account",
		)
		title = f"Scenario Illustrative Tax {rate:g}%"
		sales = context.insert(
			{
				"doctype": "Sales Taxes and Charges Template",
				"title": title,
				"company": company,
				"taxes": [
					{
						"charge_type": "On Net Total",
						"account_head": account.name,
						"rate": rate,
						"description": title,
					}
				],
			},
			capability=TAXES,
			logical_id="sales_tax_template",
		)
		purchase = context.insert(
			{
				"doctype": "Purchase Taxes and Charges Template",
				"title": title,
				"company": company,
				"taxes": [
					{
						"category": "Total",
						"add_deduct_tax": "Add",
						"charge_type": "On Net Total",
						"account_head": account.name,
						"rate": rate,
						"description": title,
					}
				],
			},
			capability=TAXES,
			logical_id="purchase_tax_template",
		)
		return {
			"rate": rate,
			"account": account.name,
			"sales_template": sales.name,
			"purchase_template": purchase.name,
			"abbr": abbr,
		}

	def _apply_credit_limits(self, context: ScenarioContext) -> list[dict[str, Any]]:
		context.current_capability = CREDIT_LIMITS
		company = context.require(COMPANY)
		customers = context.require(CUSTOMERS)
		months = float(context.section("accounting_controls").get("credit_limit_months") or 3)
		base = max(10000.0, context.country_pack.price_scale * 100000.0 * months)
		result: list[dict[str, Any]] = []
		for index, customer in enumerate(customers, 1):
			if customer.get("pays_cash"):
				continue
			doc = frappe.get_doc("Customer", customer["name"])
			limit = round(base * (1 + (index % 5) * 0.25), context.country_pack.currency_precision)
			row = next((row for row in doc.credit_limits if row.company == company), None)
			if row:
				row.credit_limit = limit
				row.bypass_credit_limit_check = 0
			else:
				doc.append(
					"credit_limits",
					{"company": company, "credit_limit": limit, "bypass_credit_limit_check": 0},
				)
			doc.save(ignore_permissions=True)
			result.append({"customer": doc.name, "credit_limit": limit})
		return result

	def _create_crm(self, context: ScenarioContext, taxes: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
		context.current_capability = CRM
		customers = context.require(CUSTOMERS)
		items = context.require(ITEMS)
		operations = context.section("operations")
		lifecycle = forecast_specification_lifecycle(context.specification)
		count = min(
			len(customers),
			max(0, round(lifecycle["sales_activities"] * float(operations.get("opportunity_ratio") or 0))),
		)
		quote_count = min(count, round(count * float(operations.get("quotation_ratio") or 0)))
		random = context.random("crm")
		opportunities: list[dict[str, Any]] = []
		quotations: list[dict[str, Any]] = []
		for index, customer in enumerate(customers[:count], 1):
			date = clamp(
				context.start_date + datetime.timedelta(days=index * 3),
				context.start_date,
				context.anchor_date,
			)
			selected = random.sample(items, min(random.randint(1, 3), len(items)))
			lines = [
				{"item_code": item["item_code"], "qty": 1, "uom": item["uom"], "rate": item["rate"]}
				for item in selected
			]
			opportunity = context.insert(
				{
					"doctype": "Opportunity",
					"opportunity_from": "Customer",
					"party_name": customer["name"],
					"opportunity_type": "Sales",
					"status": "Open",
					"company": context.require(COMPANY),
					"currency": context.currency,
					"transaction_date": date,
					"expected_closing": min(date + datetime.timedelta(days=30), context.anchor_date),
					"probability": random.choice([40, 55, 70, 85]),
					"items": lines,
				},
				capability=CRM,
				logical_id=f"opportunity:{index:04d}",
			)
			opportunities.append(
				{"name": opportunity.name, "customer": customer["name"], "date": date.isoformat()}
			)
			if index > quote_count:
				continue
			quotation = context.insert(
				{
					"doctype": "Quotation",
					"quotation_to": "Customer",
					"party_name": customer["name"],
					"company": context.require(COMPANY),
					"currency": context.currency,
					"transaction_date": date,
					"valid_till": min(date + datetime.timedelta(days=30), context.anchor_date),
					"order_type": "Sales",
					"opportunity": opportunity.name,
					"taxes_and_charges": taxes.get("sales_template"),
					"items": lines,
				},
				capability=CRM,
				submit=True,
				logical_id=f"quotation:{index:04d}",
				dependencies=[f"Opportunity/{opportunity.name}"],
			)
			quotations.append(
				{
					"name": quotation.name,
					"customer": customer["name"],
					"opportunity": opportunity.name,
					"items": [{"item_code": row.item_code, "name": row.name} for row in quotation.items],
				}
			)
		return {"opportunities": opportunities, "quotations": quotations}

	def _create_transfers(self, context: ScenarioContext) -> list[dict[str, Any]]:
		context.current_capability = TRANSFERS
		count = int(context.section("operations").get("stock_transfers") or 0)
		warehouses = context.require(WAREHOUSES)
		all_warehouses = warehouses.get("all") or []
		stock = context.require(STOCK)
		if count <= 0 or len(all_warehouses) < 2 or not stock.get("quantities"):
			return []
		items = {item["item_code"]: item for item in context.require(ITEMS)}
		random = context.random("stock_transfers")
		results: list[dict[str, Any]] = []
		for index in range(count):
			movable = [
				code for code, quantity in stock["quantities"].items() if quantity >= 2 and code in items
			]
			if not movable:
				break
			codes = random.sample(movable, min(3, len(movable)))
			lines = []
			for code in codes:
				quantity = max(1, round(float(stock["quantities"][code]) * 0.05))
				stock["quantities"][code] -= quantity
				lines.append(
					{
						"item_code": code,
						"qty": quantity,
						"s_warehouse": warehouses["default"],
						"t_warehouse": all_warehouses[(index + 1) % len(all_warehouses)],
						"uom": items[code]["uom"],
						"stock_uom": items[code]["uom"],
						"conversion_factor": 1,
					}
				)
			doc = context.insert(
				{
					"doctype": "Stock Entry",
					"stock_entry_type": "Material Transfer",
					"purpose": "Material Transfer",
					"company": context.require(COMPANY),
					"posting_date": context.start_date,
					"posting_time": "11:00:00",
					"set_posting_time": 1,
					"items": lines,
					"remarks": "Scenario inter-warehouse replenishment.",
				},
				capability=TRANSFERS,
				submit=True,
				logical_id=f"stock_transfer:{index:03d}",
			)
			results.append({"name": doc.name, "items": len(lines), "target": lines[0]["t_warehouse"]})
		return results

	def validate(self, context: ScenarioContext) -> ValidationResult:
		result = ValidationResult()
		crm = context.optional(CRM) or {}
		for quotation in crm.get("quotations") or []:
			if not quotation.get("opportunity"):
				result.error(
					"erpnext.commercial.crm_links",
					f"Quotation {quotation['name']} has no opportunity.",
					provider=self.id,
				)
		for transfer in context.optional(TRANSFERS) or []:
			if frappe.db.get_value("Stock Entry", transfer["name"], "docstatus") != 1:
				result.error(
					"erpnext.commercial.stock_transfers",
					f"Stock Entry {transfer['name']} is not submitted.",
					provider=self.id,
				)
		taxes = context.optional(TAXES) or {}
		if taxes.get("rate"):
			for doctype, field in (
				("Sales Taxes and Charges Template", "sales_template"),
				("Purchase Taxes and Charges Template", "purchase_template"),
			):
				if not taxes.get(field) or not frappe.db.exists(doctype, taxes[field]):
					result.error(
						rule="erpnext.commercial.tax_templates",
						message=f"Configured {doctype} is missing.",
						provider=self.id,
						capability=TAXES,
						doctype=doctype,
						record=taxes.get(field),
					)
		company = context.optional(COMPANY)
		for limit in context.optional(CREDIT_LIMITS) or []:
			stored = frappe.db.get_value(
				"Customer Credit Limit",
				{"parent": limit["customer"], "company": company},
				"credit_limit",
			)
			if float(stored or 0) != float(limit["credit_limit"]):
				result.error(
					rule="erpnext.commercial.credit_limits",
					message=f"Customer {limit['customer']} does not have its planned credit limit.",
					provider=self.id,
					capability=CREDIT_LIMITS,
					doctype="Customer",
					record=limit["customer"],
				)
		return result
