# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""ERPNext payments provider.

Settles a share of sales and purchase invoices with Payment Entries built by
ERPNext's own ``get_payment_entry``, and posts recurring accrual journal entries
so the profit and loss statement contains more than trading margin.

Payments land after the customer's credit period, which is what produces a
realistic ageing profile: some invoices paid on time, some late, some still open
at the anchor date.
"""

from __future__ import annotations

import datetime
from typing import Any

import frappe
from frappe.query_builder import DocType
from frappe.query_builder.functions import Sum

from frappe_scenario.core.context import ScenarioContext
from frappe_scenario.core.lifecycle import forecast_specification_lifecycle
from frappe_scenario.core.provider import (
	CapabilityDeclaration,
	ProviderResult,
	ScenarioPlan,
	ScenarioProvider,
)
from frappe_scenario.core.validation import ValidationResult
from frappe_scenario.providers.erpnext_buying import INVOICES as PURCHASE_INVOICES
from frappe_scenario.providers.erpnext_foundation import ACCOUNTS, COMPANY
from frappe_scenario.providers.erpnext_selling import INVOICES as SALES_INVOICES
from frappe_scenario.providers.erpnext_selling import RETURNS as SALES_RETURNS
from frappe_scenario.providers.support import erpnext_tools as tools
from frappe_scenario.providers.support.calendar_tools import clamp, fiscal_years, month_end, month_starts

RECEIPTS = "erpnext.accounts.customer_payments"
PAYMENTS = "erpnext.accounts.supplier_payments"
ACCRUALS = "erpnext.accounts.accruals"
BANK_RECONCILIATION = "erpnext.accounts.bank_reconciliation"
PERIOD_CLOSING = "erpnext.accounts.period_closing"

PAYMENT_ENTRY_MODULE = "erpnext.accounts.doctype.payment_entry.payment_entry"


class ErpnextPaymentsProvider(ScenarioProvider):
	id = "erpnext.payments"
	version = "0.3.0"
	title = "ERPNext Payments and Accruals"
	description = "Customer receipts, supplier payments, and recurring accrual journal entries."
	role = "extender"
	app = "frappe_scenario"
	order = 90

	requires_apps = {"erpnext": ">=15.0.0"}
	requires_capabilities = {COMPANY, ACCOUNTS}
	optional_capabilities = {SALES_INVOICES, SALES_RETURNS, PURCHASE_INVOICES}
	provides_capabilities = {RECEIPTS, PAYMENTS, ACCRUALS, BANK_RECONCILIATION, PERIOD_CLOSING}

	capabilities = [
		CapabilityDeclaration(
			id=RECEIPTS,
			description="Payment entries settling sales invoices after the customer's credit period.",
			doctypes=["Payment Entry"],
			optional_requires=[SALES_INVOICES],
			validation_rules=["erpnext.payments.receivable_reconciles", "erpnext.payments.overdue_profile"],
		),
		CapabilityDeclaration(
			id=BANK_RECONCILIATION,
			description="Bank statement transactions reconciled to generated Payment Entries.",
			doctypes=["Bank Transaction"],
			requires=[ACCOUNTS],
			optional_requires=[RECEIPTS, PAYMENTS],
			validation_rules=["erpnext.payments.bank_reconciled"],
		),
		CapabilityDeclaration(
			id=PERIOD_CLOSING,
			description="Submitted Period Closing Vouchers through the scenario anchor date.",
			doctypes=["Period Closing Voucher"],
			requires=[ACCOUNTS],
			validation_rules=["erpnext.payments.period_closed"],
		),
		CapabilityDeclaration(
			id=PAYMENTS,
			description="Payment entries settling purchase invoices.",
			doctypes=["Payment Entry"],
			optional_requires=[PURCHASE_INVOICES],
			validation_rules=["erpnext.payments.payable_reconciles"],
		),
		CapabilityDeclaration(
			id=ACCRUALS,
			description="Monthly accrual journal entries for operating overheads.",
			doctypes=["Account", "Journal Entry"],
			requires=[ACCOUNTS],
			validation_rules=["erpnext.payments.journal_balanced"],
		),
	]

	def get_options_schema(self) -> dict[str, Any]:
		return {
			"type": "object",
			"additionalProperties": False,
			"properties": {
				"partial_payment_ratio": {"type": "number", "minimum": 0, "maximum": 1},
				"monthly_overhead": {"type": "number", "minimum": 0},
			},
		}

	# -- planning ------------------------------------------------------------
	def plan(self, context: ScenarioContext) -> ScenarioPlan:
		accounting = context.section("accounting")
		lifecycle = forecast_specification_lifecycle(context.specification)
		plan = ScenarioPlan(provider=self.id)
		plan.step(
			RECEIPTS,
			f"Settle about {float(accounting.get('customer_payment_ratio') or 0.75):.0%} of sales invoices.",
			doctype="Payment Entry",
			count=lifecycle["customer_payments"],
		)
		plan.step(
			PAYMENTS,
			f"Settle about {float(accounting.get('supplier_payment_ratio') or 0.7):.0%} of purchase invoices.",
			doctype="Payment Entry",
			count=lifecycle["supplier_payments"],
		)
		if accounting.get("monthly_accruals", True):
			plan.step(
				ACCRUALS,
				"Post one operating overhead accrual per month.",
				doctype="Journal Entry",
				count=context.history_months,
			)
		controls = context.section("accounting_controls")
		reconciled = round(
			(lifecycle["customer_payments"] + lifecycle["supplier_payments"])
			* float(controls.get("bank_reconciliation_ratio") or 0)
		)
		plan.step(
			BANK_RECONCILIATION,
			"Import bank statement rows and reconcile them to generated payments.",
			doctype="Bank Transaction",
			count=reconciled,
		)
		plan.step(
			PERIOD_CLOSING,
			"Close each fiscal period represented by the generated history.",
			doctype="Period Closing Voucher",
			count=len(fiscal_years(context.start_date, context.anchor_date))
			if controls.get("period_closing")
			else 0,
		)
		if float(accounting.get("bad_debt_cases") or 0) > 0:
			plan.unsupported.append("accounting.bad_debt_cases is not implemented yet and will be ignored.")
		plan.assumptions.append(
			"Payments settle after the credit period, so unpaid invoices at the anchor date form "
			"the ageing profile."
		)
		return plan

	# -- generation ----------------------------------------------------------
	def generate(self, context: ScenarioContext) -> ProviderResult:
		result = ProviderResult(provider=self.id)
		company = context.require(COMPANY)
		accounts = context.require(ACCOUNTS)

		receipts = self._settle(
			context,
			company=company,
			accounts=accounts,
			invoices=context.optional(SALES_INVOICES) or [],
			doctype="Sales Invoice",
			capability=RECEIPTS,
			ratio=float(context.section("accounting").get("customer_payment_ratio") or 0.75),
			namespace="customer_payments",
		)
		context.publish(RECEIPTS, receipts)

		payments = self._settle(
			context,
			company=company,
			accounts=accounts,
			invoices=context.optional(PURCHASE_INVOICES) or [],
			doctype="Purchase Invoice",
			capability=PAYMENTS,
			ratio=float(context.section("accounting").get("supplier_payment_ratio") or 0.7),
			namespace="supplier_payments",
		)
		context.publish(PAYMENTS, payments)

		accruals = self._post_accruals(context, company, accounts)
		context.publish(ACCRUALS, accruals)
		bank_transactions = self._reconcile_bank(context, accounts, receipts, payments)
		context.publish(BANK_RECONCILIATION, bank_transactions)
		# Period Closing Vouchers make every earlier GL posting immutable. Drain
		# ERPNext's backdated stock valuation work before submitting them, otherwise
		# the scenario closes its own books before their stock GL can be reconciled.
		deferred = context.adapter.flush_deferred_work()
		if deferred.get("processed"):
			result.warnings.append(
				f"Ran {len(deferred['processed'])} deferred item valuation reposts before period closing."
			)
		closings = self._close_periods(context, company, accounts)
		context.publish(PERIOD_CLOSING, closings)

		result.published.extend([RECEIPTS, PAYMENTS, ACCRUALS, BANK_RECONCILIATION, PERIOD_CLOSING])
		result.summary = {
			"customer_payments": len(receipts),
			"supplier_payments": len(payments),
			"accruals": len(accruals),
			"bank_transactions": len(bank_transactions),
			"period_closings": len(closings),
		}
		return result

	def _reconcile_bank(
		self,
		context: ScenarioContext,
		accounts: dict[str, Any],
		receipts: list[dict[str, Any]],
		payments: list[dict[str, Any]],
	) -> list[dict[str, Any]]:
		context.current_capability = BANK_RECONCILIATION
		ratio = float(context.section("accounting_controls").get("bank_reconciliation_ratio") or 0)
		if ratio <= 0 or not accounts.get("bank_account"):
			return []
		entries = [
			*(dict(row, direction="deposit") for row in receipts),
			*(dict(row, direction="withdrawal") for row in payments),
		]
		count = min(len(entries), round(len(entries) * ratio))
		results: list[dict[str, Any]] = []
		for index, payment in enumerate(entries[:count], 1):
			amount = float(payment["amount"])
			payload = {
				"doctype": "Bank Transaction",
				"date": payment["posting_date"],
				"bank_account": accounts["bank_account"],
				"company": context.require(COMPANY),
				"currency": context.currency,
				"description": f"Scenario statement match for {payment['name']}",
				"reference_number": f"SCN-BANK-{index:05d}",
				"deposit": amount if payment["direction"] == "deposit" else 0,
				"withdrawal": amount if payment["direction"] == "withdrawal" else 0,
				"payment_entries": [
					{
						"payment_document": "Payment Entry",
						"payment_entry": payment["name"],
						"allocated_amount": 0,
					}
				],
			}
			doc = context.insert(
				payload,
				capability=BANK_RECONCILIATION,
				submit=True,
				logical_id=f"bank_transaction:{index:05d}",
				dependencies=[f"Payment Entry/{payment['name']}"],
			)
			results.append({"name": doc.name, "payment_entry": payment["name"], "status": doc.status})
		return results

	def _close_periods(
		self, context: ScenarioContext, company: str, accounts: dict[str, Any]
	) -> list[dict[str, Any]]:
		context.current_capability = PERIOD_CLOSING
		if not context.section("accounting_controls").get("period_closing"):
			return []
		closing_account = accounts.get("equity")
		if not closing_account:
			context.warning("Period closing was skipped because no equity closing account was resolved.")
			return []
		results: list[dict[str, Any]] = []
		for start, end in fiscal_years(context.start_date, context.anchor_date):
			period_end = min(end, context.anchor_date)
			fiscal_year = tools.fiscal_year_for(period_end, company)
			if not fiscal_year:
				continue
			doc = context.insert(
				{
					"doctype": "Period Closing Voucher",
					"transaction_date": period_end,
					"company": company,
					"fiscal_year": fiscal_year,
					"period_start_date": start,
					"period_end_date": period_end,
					"closing_account_head": closing_account,
					"remarks": f"Scenario period closing through {period_end.isoformat()}.",
				},
				capability=PERIOD_CLOSING,
				submit=True,
				logical_id=f"period_closing:{period_end.isoformat()}",
			)
			results.append({"name": doc.name, "period_end_date": period_end.isoformat()})
		return results

	# -- settlement ----------------------------------------------------------
	def _settle(
		self,
		context: ScenarioContext,
		*,
		company: str,
		accounts: dict[str, Any],
		invoices: list[dict[str, Any]],
		doctype: str,
		capability: str,
		ratio: float,
		namespace: str,
	) -> list[dict[str, Any]]:
		context.current_capability = capability
		if not invoices or ratio <= 0:
			return []

		random = context.random(namespace)
		options = self.options(context)
		partial_ratio = float(options.get("partial_payment_ratio", 0.15))
		# ``get_payment_entry`` stayed in the controller module on every supported
		# version, so the adapter resolves it in place.
		get_payment_entry = context.adapter.erpnext_mapper(
			"erpnext.accounts.doctype.payment_entry", "get_payment_entry"
		)

		bank = accounts.get("bank")
		settled: list[dict[str, Any]] = []

		for invoice in invoices:
			if not random.chance(ratio):
				continue

			outstanding = frappe.db.get_value(doctype, invoice["name"], "outstanding_amount")
			if not outstanding or float(outstanding) <= 0:
				continue

			invoice_date = datetime.date.fromisoformat(invoice["posting_date"])
			credit_days = int(invoice.get("credit_days") or 0)
			# Settle against the due date ERPNext actually derived from the payment
			# terms template, falling back to the term's credit days if the invoice
			# carries no due date.
			if invoice.get("due_date"):
				due_date = datetime.date.fromisoformat(invoice["due_date"])
			else:
				due_date = invoice_date + datetime.timedelta(days=credit_days)
			# Most parties pay a little after terms; a few pay early.
			drift = random.randint(-3, max(3, credit_days // 2))
			payment_date = max(due_date + datetime.timedelta(days=drift), invoice_date)
			if payment_date > context.anchor_date:
				# Not yet paid as at the anchor date. Leaving it outstanding is what
				# gives the receivables and payables their ageing profile, so it must
				# not be clamped forward onto the anchor date.
				continue

			amount = float(outstanding)
			if random.chance(partial_ratio):
				amount = round(
					amount * random.uniform(0.3, 0.8), int(accounts.get("currency_precision") or 2)
				)
			if amount <= 0:
				continue

			doc = get_payment_entry(doctype, invoice["name"], bank_account=bank)
			doc.posting_date = payment_date
			doc.reference_no = f"PAY-{invoice['name']}"
			doc.reference_date = payment_date
			_allocate(doc, amount)

			context.insert_doc(
				doc,
				capability=capability,
				submit=True,
				logical_id=f"payment:{invoice['name']}",
				dependencies=[f"{doctype}/{invoice['name']}"],
			)

			settled.append(
				{
					"name": doc.name,
					"invoice": invoice["name"],
					"invoice_doctype": doctype,
					"posting_date": payment_date.isoformat(),
					"amount": amount,
					"partial": amount < float(outstanding),
				}
			)

		return settled

	# -- accruals ------------------------------------------------------------
	def _post_accruals(
		self, context: ScenarioContext, company: str, accounts: dict[str, Any]
	) -> list[dict[str, Any]]:
		context.current_capability = ACCRUALS
		accounting = context.section("accounting")
		if not accounting.get("monthly_accruals", True):
			return []

		random = context.random("accruals")
		precision = int(accounts.get("currency_precision") or 2)
		# The payable control account demands a party on every entry, so accruals
		# post to a dedicated liability ledger instead.
		expense = self._ensure_account(
			context,
			company=company,
			account_name="Scenario Operating Overheads",
			parent=tools.account_group(company, account_name="Indirect Expenses", root_type="Expense"),
			root_type="Expense",
		)
		liability = self._ensure_account(
			context,
			company=company,
			account_name="Scenario Accrued Expenses",
			parent=tools.account_group(company, account_name="Current Liabilities", root_type="Liability"),
			root_type="Liability",
		)
		if not expense or not liability:
			context.warning("Skipped monthly accruals: the chart of accounts has no usable expense group.")
			return []

		base = float(self.options(context).get("monthly_overhead") or 0) or round(
			max(500.0, 250.0 * context.country_pack.price_scale * 4), precision
		)

		entries: list[dict[str, Any]] = []
		for month in month_starts(context.start_date, context.history_months):
			posting_date = clamp(month_end(month), context.start_date, context.anchor_date)
			amount = round(base * random.uniform(0.85, 1.2), precision)
			doc = context.insert(
				{
					"doctype": "Journal Entry",
					"voucher_type": "Journal Entry",
					"company": company,
					"posting_date": posting_date,
					"user_remark": f"Operating overheads accrued for {month.strftime('%B %Y')}.",
					"accounts": [
						{
							"account": expense,
							"debit_in_account_currency": amount,
							"cost_center": accounts.get("cost_center"),
						},
						{
							"account": liability,
							"credit_in_account_currency": amount,
							"cost_center": accounts.get("cost_center"),
						},
					],
				},
				capability=ACCRUALS,
				submit=True,
				logical_id=f"accrual:{month.isoformat()[:7]}",
			)
			entries.append({"name": doc.name, "posting_date": posting_date.isoformat(), "amount": amount})

		return entries

	def _ensure_account(
		self,
		context: ScenarioContext,
		*,
		company: str,
		account_name: str,
		parent: str | None,
		root_type: str,
	) -> str | None:
		"""Create a scenario-owned ledger account under an existing group."""
		if not parent:
			return None
		existing = frappe.db.get_value(
			"Account", {"company": company, "account_name": account_name, "is_group": 0}, "name"
		)
		if existing:
			return existing
		doc = context.insert(
			{
				"doctype": "Account",
				"company": company,
				"account_name": account_name,
				"parent_account": parent,
				"root_type": root_type,
				"is_group": 0,
				"account_currency": context.currency,
			},
			capability=ACCRUALS,
			logical_id=f"account:{account_name}",
		)
		return doc.name

	# -- validation ----------------------------------------------------------
	def validate(self, context: ScenarioContext) -> ValidationResult:
		result = ValidationResult()
		company = context.optional(COMPANY)
		accounts = context.optional(ACCOUNTS) or {}
		if not company:
			return result

		# The payable control account also carries accrued overheads, so only the
		# receivable side can be reconciled against invoices alone here. The
		# payable side is covered by the cross-provider ledger validators.
		self._validate_receivable(context, company, accounts.get("receivable"), result)
		self._validate_journals(context, result)
		self._validate_overdue(context, result)
		self._validate_bank_reconciliation(context, result)
		self._validate_period_closing(context, result)
		return result

	def _validate_bank_reconciliation(self, context: ScenarioContext, result: ValidationResult) -> None:
		for entry in context.optional(BANK_RECONCILIATION) or []:
			doc = frappe.db.get_value(
				"Bank Transaction", entry["name"], ["docstatus", "status"], as_dict=True
			)
			if not doc or doc.docstatus != 1 or doc.status != "Reconciled":
				result.error(
					rule="erpnext.payments.bank_reconciliation",
					message=f"Bank Transaction {entry['name']} is not reconciled.",
					provider=self.id,
					capability=BANK_RECONCILIATION,
					doctype="Bank Transaction",
					record=entry["name"],
					observed=doc,
				)

	def _validate_period_closing(self, context: ScenarioContext, result: ValidationResult) -> None:
		for entry in context.optional(PERIOD_CLOSING) or []:
			if frappe.db.get_value("Period Closing Voucher", entry["name"], "docstatus") != 1:
				result.error(
					rule="erpnext.payments.period_closing",
					message=f"Period Closing Voucher {entry['name']} is not submitted.",
					provider=self.id,
					capability=PERIOD_CLOSING,
					doctype="Period Closing Voucher",
					record=entry["name"],
				)

	def _validate_receivable(
		self,
		context: ScenarioContext,
		company: str,
		account: str | None,
		result: ValidationResult,
	) -> None:
		"""The receivable control account must equal the sum of open sales invoices."""
		invoices = context.optional(SALES_INVOICES) or []
		if not account or not invoices:
			return

		credit_notes = [
			entry["name"]
			for entry in context.optional(SALES_RETURNS) or []
			if entry.get("doctype") == "Sales Invoice"
		]
		names = [invoice["name"] for invoice in invoices] + credit_notes
		outstanding = sum(
			float(row.outstanding_amount or 0)
			for row in frappe.get_all(
				"Sales Invoice",
				filters={"name": ("in", names), "docstatus": 1},
				fields=["outstanding_amount"],
			)
		)
		balance = _account_balance(company, account)

		if abs(balance - outstanding) > 0.5:
			result.error(
				rule="erpnext.payments.receivable_reconciles",
				message=(f"{account} shows {balance:.2f} but open sales invoices total {outstanding:.2f}."),
				provider=self.id,
				capability=RECEIPTS,
				doctype="Account",
				record=account,
				observed=round(balance, 2),
				expected=round(outstanding, 2),
				remediation="Investigate payment allocation or manual ledger entries.",
			)

	def _validate_journals(self, context: ScenarioContext, result: ValidationResult) -> None:
		for entry in context.optional(ACCRUALS) or []:
			doc = frappe.db.get_value(
				"Journal Entry", entry["name"], ["total_debit", "total_credit", "docstatus"], as_dict=True
			)
			if not doc:
				continue
			if doc.docstatus != 1 or round(float(doc.total_debit) - float(doc.total_credit), 4) != 0:
				result.error(
					rule="erpnext.payments.journal_balanced",
					message=f"Journal Entry {entry['name']} is unbalanced or not submitted.",
					provider=self.id,
					capability=ACCRUALS,
					doctype="Journal Entry",
					record=entry["name"],
					observed=[doc.total_debit, doc.total_credit, doc.docstatus],
				)

	def _validate_overdue(self, context: ScenarioContext, result: ValidationResult) -> None:
		requested = float(context.section("accounting").get("overdue_receivables") or 0)
		invoices = context.optional(SALES_INVOICES) or []
		if not invoices:
			return

		names = [invoice["name"] for invoice in invoices]
		overdue = frappe.get_all(
			"Sales Invoice",
			filters={
				"name": ("in", names),
				"docstatus": 1,
				"outstanding_amount": (">", 0),
				"due_date": ("<", context.anchor_date),
			},
			pluck="name",
		)
		share = len(overdue) / len(invoices)

		if requested <= 0 and share > 0:
			result.info(
				rule="erpnext.payments.overdue_profile",
				message=(
					f"{share:.1%} of sales invoices are past due at the anchor date, which follows "
					"from the payment ratio rather than an explicit request."
				),
				provider=self.id,
				capability=RECEIPTS,
				observed=round(share, 4),
			)
		elif requested > 0 and share < requested * 0.5:
			result.warning(
				rule="erpnext.payments.overdue_profile",
				message=f"Requested {requested:.1%} overdue receivables but only {share:.1%} are overdue.",
				provider=self.id,
				capability=RECEIPTS,
				observed=round(share, 4),
				expected=requested,
			)


def _account_balance(company: str, account: str) -> float:
	"""Net debit balance of a ledger account, read through the query builder."""
	gl = DocType("GL Entry")
	rows = (
		frappe.qb.from_(gl)
		.select((Sum(gl.debit) - Sum(gl.credit)).as_("balance"))
		.where(gl.company == company)
		.where(gl.account == account)
		.where(gl.is_cancelled == 0)
		.run(as_dict=True)
	)
	return float(rows[0].balance or 0) if rows else 0.0


def _allocate(doc: Any, amount: float) -> None:
	"""Constrain a payment entry to the amount actually being settled."""
	if not doc.references:
		return
	reference = doc.references[0]
	reference.allocated_amount = amount
	doc.paid_amount = amount
	doc.received_amount = amount
	if doc.meta.has_field("base_paid_amount"):
		doc.base_paid_amount = amount
	if doc.meta.has_field("base_received_amount"):
		doc.base_received_amount = amount
	doc.set("deductions", [])
