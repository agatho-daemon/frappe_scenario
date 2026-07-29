# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""ERPNext foundation provider.

Creates the company and the accounting scaffolding every later provider needs:
fiscal years covering the scenario window, a bank account, and payment terms
templates matching the specification's credit mix.

The company is created through the normal Company controller, so ERPNext's own
chart of accounts, default warehouses, and cost centres are produced by ERPNext
rather than reimplemented here.
"""

from __future__ import annotations

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
from frappe_scenario.providers.support import erpnext_tools as tools
from frappe_scenario.providers.support.calendar_tools import fiscal_years

COMPANY = "erpnext.foundation.company"
MASTERS = "erpnext.foundation.masters"
FISCAL_YEARS = "erpnext.foundation.fiscal_years"
ACCOUNTS = "erpnext.foundation.accounts"
PAYMENT_TERMS = "erpnext.foundation.payment_terms"

#: ``{specification key: credit days}``. Keys come from ``parties.payment_terms``.
CREDIT_DAYS = {
	"cash": 0,
	"immediate": 0,
	"net_7": 7,
	"net_15": 15,
	"net_30": 30,
	"net_45": 45,
	"net_60": 60,
	"net_90": 90,
	"net_120": 120,
}


class ErpnextFoundationProvider(ScenarioProvider):
	id = "erpnext.foundation"
	version = "0.1.0"
	title = "ERPNext Foundation"
	description = "Company, fiscal years, bank account, and payment terms templates."
	role = "provider"
	app = "frappe_scenario"
	order = 20

	requires_apps = {"erpnext": ">=15.0.0"}
	requires_capabilities = {"frappe.foundation.settings"}
	provides_capabilities = {MASTERS, COMPANY, FISCAL_YEARS, ACCOUNTS, PAYMENT_TERMS}

	capabilities = [
		CapabilityDeclaration(
			id=MASTERS,
			description="Installs ERPNext's own setup-wizard master records when the site lacks them.",
			doctypes=["Warehouse Type", "Item Group", "UOM", "Accounts Settings"],
			requires=["frappe.foundation.settings"],
			estimated_records="ERPNext's standard fixture set, only on a site that never ran the setup wizard",
			validation_rules=["erpnext.foundation.masters_present"],
		),
		CapabilityDeclaration(
			id=COMPANY,
			description="Creates the scenario company with ERPNext's standard chart of accounts.",
			doctypes=["Company"],
			requires=[MASTERS],
			estimated_records="1 Company plus the accounts, warehouses, and cost centres "
			"ERPNext creates for it",
			validation_rules=["erpnext.foundation.company_exists", "erpnext.foundation.chart_installed"],
		),
		CapabilityDeclaration(
			id=FISCAL_YEARS,
			description="Ensures fiscal years cover the whole scenario history window.",
			doctypes=["Fiscal Year"],
			requires=[COMPANY],
			validation_rules=["erpnext.foundation.fiscal_year_coverage"],
		),
		CapabilityDeclaration(
			id=ACCOUNTS,
			description="Creates a bank ledger account and its Bank Account record.",
			doctypes=["Account", "Bank", "Bank Account"],
			requires=[COMPANY],
			validation_rules=["erpnext.foundation.bank_account"],
		),
		CapabilityDeclaration(
			id=PAYMENT_TERMS,
			description="Creates Payment Term and Payment Terms Template records for the credit mix.",
			doctypes=["Payment Term", "Payment Terms Template"],
			requires=[COMPANY],
		),
	]

	def get_options_schema(self) -> dict[str, Any]:
		return {
			"type": "object",
			"additionalProperties": False,
			"properties": {
				"chart_of_accounts": {"type": "string"},
				"bank_name": {"type": "string"},
				"reuse_existing_company": {"type": "boolean"},
			},
		}

	# -- planning ------------------------------------------------------------
	def plan(self, context: ScenarioContext) -> ScenarioPlan:
		plan = ScenarioPlan(provider=self.id)
		years = fiscal_years(context.start_date, context.anchor_date)
		terms = sorted((context.section("parties").get("payment_terms") or {}).keys())

		plan.step(
			MASTERS,
			"Install ERPNext's setup-wizard master records if this site does not already have them.",
			doctype="Warehouse Type",
			count=0 if _masters_present() else 1,
		)
		plan.step(
			COMPANY, "Create the scenario company and its chart of accounts.", doctype="Company", count=1
		)
		plan.step(
			FISCAL_YEARS,
			f"Ensure fiscal years exist for {years[0][0].year}-{years[-1][1].year}.",
			doctype="Fiscal Year",
			count=len(years),
		)
		plan.step(
			ACCOUNTS,
			"Create a bank ledger account and Bank Account record.",
			doctype="Bank Account",
			count=3,
		)
		plan.step(
			PAYMENT_TERMS,
			f"Create payment terms templates: {', '.join(terms) or 'none'}.",
			doctype="Payment Terms Template",
			count=len(terms) * 2,
		)

		unknown = [term for term in terms if term not in CREDIT_DAYS]
		if unknown:
			plan.unsupported.append(
				f"Unknown payment term keys will be treated as immediate payment: {', '.join(unknown)}"
			)
		plan.assumptions.append(
			"Fiscal years are calendar-aligned. No country-specific fiscal calendar is claimed."
		)
		plan.assumptions.append(
			"ERPNext's standard chart of accounts is used. No country-specific chart is installed "
			"and no tax templates are created."
		)
		if not _masters_present():
			plan.assumptions.append(
				"This site has never run the ERPNext setup wizard, so ERPNext's own master fixtures "
				"will be installed first. They are site-level records and are not removed by cleanup."
			)
		plan.cleanup_notes.append(
			"Deleting the company cascades to the accounts, cost centres, and warehouses ERPNext "
			"created for it, once its transactions are gone."
		)
		return plan

	# -- generation ----------------------------------------------------------
	def generate(self, context: ScenarioContext) -> ProviderResult:
		result = ProviderResult(provider=self.id)

		masters = self._ensure_erpnext_masters(context)
		masters["ledger_deletion_enabled"] = self._enable_ledger_deletion(context)
		context.publish(MASTERS, masters)
		result.published.append(MASTERS)

		company = self._create_company(context)
		context.publish(COMPANY, company)
		result.published.append(COMPANY)

		years = self._ensure_fiscal_years(context)
		context.publish(FISCAL_YEARS, years)
		result.published.append(FISCAL_YEARS)

		accounts = self._create_accounts(context, company)
		context.publish(ACCOUNTS, accounts)
		result.published.append(ACCOUNTS)

		terms = self._create_payment_terms(context)
		context.publish(PAYMENT_TERMS, terms)
		result.published.append(PAYMENT_TERMS)

		result.summary = {"company": company, "fiscal_years": years, "accounts": accounts}
		return result

	def _ensure_erpnext_masters(self, context: ScenarioContext) -> dict[str, Any]:
		"""Install ERPNext's setup-wizard fixtures when the site has never had them.

		A site built with ``bench new-site`` plus ``install-app erpnext`` has every
		ERPNext DocType but none of the records the setup wizard normally creates.
		The Company controller links to ``Warehouse Type`` "Transit" the moment it
		is saved, so company creation fails outright on such a site.

		We call ERPNext's own installer instead of reproducing its records, which
		keeps this correct across versions. The records are site-level masters
		shared by everything on the site, so they are deliberately not recorded in
		the run manifest and cleanup leaves them alone.
		"""
		context.current_capability = MASTERS
		if _masters_present():
			return {"installed": False, "reason": "ERPNext master records already present."}

		from erpnext.setup.setup_wizard.operations.install_fixtures import install

		install(context.country_pack.country)
		context.warning(
			"Installed ERPNext's setup-wizard master records because this site did not have them. "
			"They are site-level records and are not removed by scenario cleanup."
		)
		context.progress("Installed ERPNext master records.")
		return {"installed": True, "country": context.country_pack.country}

	def _enable_ledger_deletion(self, context: ScenarioContext) -> bool:
		"""Let ERPNext remove a voucher's ledger entries when the voucher is deleted.

		ERPNext only deletes the GL, Payment Ledger, and Stock Ledger rows behind a
		document when ``Accounts Settings.delete_linked_ledger_entries`` is on.
		With it off, cleanup cancels a document, tries to delete it, and Frappe
		refuses because those ledger rows still link to it, so a run could never
		remove its own data. The previous value is recorded, so cleanup restores
		whatever the site had.
		"""
		doctype = "Accounts Settings"
		field = "delete_linked_ledger_entries"
		if not context.adapter.has_field(doctype, field):
			context.warning(
				f"{doctype} has no {field} field on this version, so cleanup may be unable "
				"to delete submitted documents."
			)
			return False

		current = frappe.db.get_single_value(doctype, field)
		if current:
			return False

		context.record_modified(frappe.get_single(doctype), {field: current}, capability=MASTERS)
		frappe.db.set_single_value(doctype, field, 1)
		frappe.clear_document_cache(doctype, doctype)
		context.progress(f"Enabled {doctype}.{field} so cleanup can remove its own documents.")
		return True

	def _create_company(self, context: ScenarioContext) -> str:
		context.current_capability = COMPANY
		spec = context.section("company")
		options = self.options(context)
		random = context.random("company")
		pack = context.country_pack

		name = spec.get("name") or pack.company_name(random)
		if frappe.db.exists("Company", name):
			if not options.get("reuse_existing_company"):
				raise ProviderError(
					f"Company {name!r} already exists on this site.",
					provider=self.id,
					capability=COMPANY,
					phase="generate",
					record=f"Company/{name}",
					details={
						"remediation": (
							"Choose a different company.name, clean up the previous run, or set "
							"providers['erpnext.foundation'].reuse_existing_company."
						)
					},
				)
			context.warning(f"Reusing the existing company {name!r}; it is not owned by this run.")
			return name

		abbr = spec.get("abbr") or _derive_abbr(name)
		doc = context.insert(
			{
				"doctype": "Company",
				"company_name": name,
				"abbr": abbr,
				"default_currency": context.currency,
				"country": pack.country,
				"create_chart_of_accounts_based_on": "Standard Template",
				"chart_of_accounts": options.get("chart_of_accounts") or "Standard",
				"enable_perpetual_inventory": 1 if spec.get("enable_perpetual_inventory", True) else 0,
				"domain": spec.get("industry") or "Distribution",
			},
			capability=COMPANY,
			logical_id="company",
		)
		context.progress(f"Created company {doc.name}.")
		return doc.name

	def _ensure_fiscal_years(self, context: ScenarioContext) -> list[str]:
		context.current_capability = FISCAL_YEARS
		names: list[str] = []
		for start, end in fiscal_years(context.start_date, context.anchor_date):
			existing = frappe.db.get_value(
				"Fiscal Year", {"year_start_date": start, "year_end_date": end}, "name"
			)
			if existing:
				names.append(existing)
				continue
			doc = context.insert(
				{
					"doctype": "Fiscal Year",
					"year": str(start.year),
					"year_start_date": start,
					"year_end_date": end,
				},
				capability=FISCAL_YEARS,
				logical_id=f"fiscal_year:{start.year}",
			)
			names.append(doc.name)
		return names

	def _create_accounts(self, context: ScenarioContext, company: str) -> dict[str, Any]:
		context.current_capability = ACCOUNTS
		options = self.options(context)
		random = context.random("accounts")
		pack = context.country_pack

		abbr = tools.company_abbr(company)
		bank_group = tools.account_group(company, account_name="Bank Accounts", root_type="Asset")
		if not bank_group:
			raise ProviderError(
				"Could not locate a Bank Accounts group in the company's chart of accounts.",
				provider=self.id,
				capability=ACCOUNTS,
				phase="generate",
			)

		bank_name = options.get("bank_name") or f"{random.choice(['Gulf', 'Meridian', 'Harbor'])} Bank"
		if not frappe.db.exists("Bank", bank_name):
			context.insert(
				{"doctype": "Bank", "bank_name": bank_name},
				capability=ACCOUNTS,
				logical_id="bank",
			)

		ledger = context.insert(
			{
				"doctype": "Account",
				"account_name": f"{bank_name} Current Account",
				"parent_account": bank_group,
				"company": company,
				"account_type": "Bank",
				"account_currency": context.currency,
				"is_group": 0,
			},
			capability=ACCOUNTS,
			logical_id="bank_ledger",
		)

		bank_account = context.insert(
			{
				"doctype": "Bank Account",
				"account_name": f"{bank_name} Current Account",
				"bank": bank_name,
				"account": ledger.name,
				"company": company,
				"is_company_account": 1,
			},
			capability=ACCOUNTS,
			logical_id="bank_account",
		)

		accounts = {
			"abbr": abbr,
			"bank": ledger.name,
			"bank_account": bank_account.name,
			"cash": tools.find_account(company, account_name="Cash", account_type="Cash"),
			"receivable": tools.find_account(company, account_type="Receivable"),
			"payable": tools.find_account(company, account_type="Payable"),
			"stock_in_hand": tools.find_account(company, account_type="Stock"),
			"equity": tools.find_account(
				company,
				account_names=["Capital Stock", "Opening Balance Equity", "Retained Earnings"],
				root_type="Equity",
			),
			"cost_center": tools.default_cost_center(company),
			"warehouse_root": tools.warehouse_root(company),
			"currency_precision": pack.currency_precision,
		}
		missing = [key for key in ("receivable", "payable", "cost_center") if not accounts.get(key)]
		if missing:
			raise ProviderError(
				f"The company chart of accounts is missing required accounts: {', '.join(missing)}.",
				provider=self.id,
				capability=ACCOUNTS,
				phase="generate",
				details={"accounts": accounts},
			)
		return accounts

	def _create_payment_terms(self, context: ScenarioContext) -> dict[str, str]:
		context.current_capability = PAYMENT_TERMS
		terms: dict[str, str] = {}
		for key in sorted((context.section("parties").get("payment_terms") or {}).keys()):
			days = CREDIT_DAYS.get(key, 0)
			label = "Cash" if days == 0 else f"Net {days} Days"
			term_name = f"Scenario {label}"

			if not frappe.db.exists("Payment Term", term_name):
				context.insert(
					{
						"doctype": "Payment Term",
						"payment_term_name": term_name,
						"due_date_based_on": "Day(s) after invoice date",
						"invoice_portion": 100,
						"credit_days": days,
					},
					capability=PAYMENT_TERMS,
					logical_id=f"payment_term:{key}",
				)

			template_name = f"Scenario {label} Template"
			if not frappe.db.exists("Payment Terms Template", template_name):
				context.insert(
					{
						"doctype": "Payment Terms Template",
						"template_name": template_name,
						"terms": [
							{
								"doctype": "Payment Terms Template Detail",
								"payment_term": term_name,
								"due_date_based_on": "Day(s) after invoice date",
								"invoice_portion": 100,
								"credit_days": days,
							}
						],
					},
					capability=PAYMENT_TERMS,
					logical_id=f"payment_terms_template:{key}",
				)
			terms[key] = template_name
		return terms

	# -- validation ----------------------------------------------------------
	def validate(self, context: ScenarioContext) -> ValidationResult:
		result = ValidationResult()
		company = context.optional(COMPANY)
		if not company or not frappe.db.exists("Company", company):
			result.error(
				rule="erpnext.foundation.company_exists",
				message="The scenario company does not exist.",
				provider=self.id,
				capability=COMPANY,
				doctype="Company",
				record=company,
			)
			return result

		leaf_accounts = frappe.db.count("Account", {"company": company, "is_group": 0})
		if leaf_accounts < 10:
			result.error(
				rule="erpnext.foundation.chart_installed",
				message=f"Company {company} has only {leaf_accounts} ledger accounts.",
				provider=self.id,
				capability=COMPANY,
				observed=leaf_accounts,
				expected=">= 10",
				remediation="Reinstall the chart of accounts for this company.",
			)

		self._validate_fiscal_coverage(context, company, result)
		self._validate_bank(context, company, result)
		return result

	def _validate_fiscal_coverage(
		self, context: ScenarioContext, company: str, result: ValidationResult
	) -> None:
		for boundary in (context.start_date, context.anchor_date):
			if not tools.fiscal_year_for(boundary, company):
				result.error(
					rule="erpnext.foundation.fiscal_year_coverage",
					message=f"No fiscal year covers {boundary.isoformat()}.",
					provider=self.id,
					capability=FISCAL_YEARS,
					observed=boundary.isoformat(),
					remediation="Create a Fiscal Year covering the scenario window.",
				)

	def _validate_bank(self, context: ScenarioContext, company: str, result: ValidationResult) -> None:
		accounts = context.optional(ACCOUNTS) or {}
		bank = accounts.get("bank")
		if not bank or not frappe.db.exists("Account", bank):
			result.error(
				rule="erpnext.foundation.bank_account",
				message="The scenario bank ledger account is missing.",
				provider=self.id,
				capability=ACCOUNTS,
				doctype="Account",
				record=bank,
			)


def _masters_present() -> bool:
	"""Whether ERPNext's setup-wizard fixtures already exist on this site.

	Warehouse Type "Transit" is the record the Company controller needs first, so
	it is a reliable and cheap marker for the whole fixture set.
	"""
	return bool(frappe.db.exists("Warehouse Type", "Transit"))


def _derive_abbr(name: str) -> str:
	words = [word for word in "".join(c if c.isalnum() or c.isspace() else " " for c in name).split() if word]
	letters = "".join(word[0] for word in words).upper()
	candidate = (letters or "SCN")[:5]
	suffix = 1
	base = candidate
	while frappe.db.exists("Company", {"abbr": candidate}):
		suffix += 1
		candidate = f"{base[:4]}{suffix}"
	return candidate
