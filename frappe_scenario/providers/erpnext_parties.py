# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""ERPNext party provider.

Customer and supplier masters, their groups, territories, addresses, and
contacts. Segments and credit terms come from the specification, so the mix of
contractor credit customers and retail cash customers is a scenario decision
rather than something hard-coded here.

Locale conventions - address shape, telephone format, and the reserved e-mail
domain - are delegated entirely to the country pack.
"""

from __future__ import annotations

from typing import Any

import frappe

from frappe_scenario.core.context import ScenarioContext
from frappe_scenario.core.provider import (
	CapabilityDeclaration,
	ProviderResult,
	ScenarioPlan,
	ScenarioProvider,
)
from frappe_scenario.core.validation import ValidationResult
from frappe_scenario.providers.erpnext_foundation import COMPANY, PAYMENT_TERMS
from frappe_scenario.providers.support.naming import party_name, person_name, slugify, unique_name

GROUPS = "erpnext.parties.groups"
CUSTOMERS = "erpnext.parties.customers"
SUPPLIERS = "erpnext.parties.suppliers"
LEADS = "erpnext.parties.leads"

#: Segments that buy on account rather than paying at the counter.
CREDIT_SEGMENTS = {
	"mep_contractor",
	"maintenance_contractor",
	"facilities_management",
	"government_project",
	"wholesale",
}

#: Payment term keys that mean "settled at the counter", with no receivable.
CASH_TERMS = {"cash", "immediate"}


class ErpnextPartiesProvider(ScenarioProvider):
	id = "erpnext.parties"
	version = "0.1.0"
	title = "ERPNext Parties"
	description = "Customers, suppliers, leads, and their groups, addresses, and contacts."
	role = "provider"
	app = "frappe_scenario"
	order = 40

	requires_apps = {"erpnext": ">=15.0.0"}
	requires_capabilities = {COMPANY, PAYMENT_TERMS}
	provides_capabilities = {GROUPS, CUSTOMERS, SUPPLIERS, LEADS}

	capabilities = [
		CapabilityDeclaration(
			id=GROUPS,
			description="Customer groups, supplier groups, and territories derived from the specification.",
			doctypes=["Customer Group", "Supplier Group", "Territory"],
			requires=[COMPANY],
		),
		CapabilityDeclaration(
			id=CUSTOMERS,
			description="Customers with segment, credit terms, address, and primary contact.",
			doctypes=["Customer", "Address", "Contact"],
			requires=[GROUPS, PAYMENT_TERMS],
			validation_rules=["erpnext.parties.customer_count", "erpnext.parties.credit_terms"],
		),
		CapabilityDeclaration(
			id=SUPPLIERS,
			description="Suppliers with group, address, contact, and a lead-time character.",
			doctypes=["Supplier", "Address", "Contact"],
			requires=[GROUPS],
			validation_rules=["erpnext.parties.supplier_count"],
		),
		CapabilityDeclaration(
			id=LEADS,
			description="Open sales leads that have not yet become customers.",
			doctypes=["Lead"],
			requires=[GROUPS],
		),
	]

	def get_options_schema(self) -> dict[str, Any]:
		return {
			"type": "object",
			"additionalProperties": False,
			"properties": {
				"create_contacts": {"type": "boolean"},
				"create_addresses": {"type": "boolean"},
				"primary_locale_share": {"type": "number", "minimum": 0, "maximum": 1},
			},
		}

	# -- planning ------------------------------------------------------------
	def plan(self, context: ScenarioContext) -> ScenarioPlan:
		parties = context.section("parties")
		customers = int(parties.get("customers") or 0)
		suppliers = int(parties.get("suppliers") or 0)
		leads = int(parties.get("leads") or 0)
		segments = sorted((parties.get("customer_segments") or {}).keys())

		plan = ScenarioPlan(provider=self.id)
		plan.step(
			GROUPS,
			f"Create customer groups ({', '.join(segments) or 'none'}), a supplier group, and territories.",
			doctype="Customer Group",
			count=len(segments) + 1 + max(len(context.country_pack.regions), 1),
		)
		plan.step(
			CUSTOMERS,
			f"Create {customers} customers with addresses and contacts.",
			doctype="Customer",
			count=customers * 3,
		)
		plan.step(
			SUPPLIERS,
			f"Create {suppliers} suppliers with addresses and contacts.",
			doctype="Supplier",
			count=suppliers * 3,
		)
		plan.step(LEADS, f"Create {leads} open leads.", doctype="Lead", count=leads)
		plan.assumptions.append(
			"E-mail addresses use the reserved .example domain, so generated data can never reach "
			"a real mailbox."
		)
		plan.assumptions.append("No national identification numbers of any kind are generated.")
		return plan

	# -- generation ----------------------------------------------------------
	def generate(self, context: ScenarioContext) -> ProviderResult:
		result = ProviderResult(provider=self.id)

		groups = self._create_groups(context)
		context.publish(GROUPS, groups)
		result.published.append(GROUPS)

		customers = self._create_customers(context, groups)
		context.publish(CUSTOMERS, customers)
		result.published.append(CUSTOMERS)

		suppliers = self._create_suppliers(context, groups)
		context.publish(SUPPLIERS, suppliers)
		result.published.append(SUPPLIERS)

		leads = self._create_leads(context, groups)
		context.publish(LEADS, leads)
		result.published.append(LEADS)

		result.summary = {
			"customers": len(customers),
			"suppliers": len(suppliers),
			"leads": len(leads),
		}
		return result

	# -- groups --------------------------------------------------------------
	def _create_groups(self, context: ScenarioContext) -> dict[str, Any]:
		context.current_capability = GROUPS
		parties = context.section("parties")
		pack = context.country_pack

		root_customer_group = _root("Customer Group")
		root_supplier_group = _root("Supplier Group")
		root_territory = _root("Territory")

		customer_groups: dict[str, str] = {}
		for segment in sorted((parties.get("customer_segments") or {}).keys()):
			title = _titleise(segment)
			customer_groups[segment] = self._ensure(
				context,
				"Customer Group",
				title,
				{
					"doctype": "Customer Group",
					"customer_group_name": title,
					"parent_customer_group": root_customer_group,
					"is_group": 0,
				},
				logical_id=f"customer_group:{segment}",
			)

		supplier_group = self._ensure(
			context,
			"Supplier Group",
			"Scenario Suppliers",
			{
				"doctype": "Supplier Group",
				"supplier_group_name": "Scenario Suppliers",
				"parent_supplier_group": root_supplier_group,
				"is_group": 0,
			},
			logical_id="supplier_group",
		)

		territories: list[str] = []
		for region in pack.regions or (pack.country,):
			territories.append(
				self._ensure(
					context,
					"Territory",
					region,
					{
						"doctype": "Territory",
						"territory_name": region,
						"parent_territory": root_territory,
						"is_group": 0,
					},
					logical_id=f"territory:{slugify(region)}",
				)
			)

		return {
			"customer_groups": customer_groups,
			"supplier_group": supplier_group,
			"territories": territories,
		}

	def _ensure(
		self,
		context: ScenarioContext,
		doctype: str,
		name: str,
		payload: dict[str, Any],
		*,
		logical_id: str | None = None,
	) -> str:
		"""Create a master only if it is absent; never adopt ownership of an existing one."""
		if frappe.db.exists(doctype, name):
			return name
		doc = context.insert(payload, capability=context.current_capability, logical_id=logical_id)
		return doc.name

	# -- customers -----------------------------------------------------------
	def _create_customers(self, context: ScenarioContext, groups: dict[str, Any]) -> list[dict[str, Any]]:
		context.current_capability = CUSTOMERS
		parties = context.section("parties")
		options = self.options(context)
		random = context.random("customers")
		primary = context.faker("customers", context.locale)
		secondary = context.faker("customers_secondary", context.secondary_locale)
		terms = context.require(PAYMENT_TERMS)

		count = int(parties.get("customers") or 0)
		segments = parties.get("customer_segments") or {}
		allocation = random.distribute(count, segments) if segments and count else {}

		taken: set[str] = set()
		customers: list[dict[str, Any]] = []
		index = 0

		for segment in sorted(allocation):
			for _ in range(allocation[segment]):
				index += 1
				base = party_name(
					random, primary, secondary, primary_share=float(options.get("primary_locale_share", 0.6))
				)
				name = unique_name(base, taken)
				while frappe.db.exists("Customer", name):
					name = unique_name(base, taken)

				term_key = random.weighted_key(parties.get("payment_terms") or {"cash": 1})
				if segment not in CREDIT_SEGMENTS:
					term_key = "cash"
				elif term_key in CASH_TERMS:
					# A contractor or a government project does not pay at the counter.
					# Redraw within the credit terms rather than forcing one, so the
					# specification's relative weighting still shapes the result.
					credit_only = {
						key: weight
						for key, weight in (parties.get("payment_terms") or {}).items()
						if key not in CASH_TERMS
					}
					if credit_only:
						term_key = random.weighted_key(credit_only)

				doc = context.insert(
					{
						"doctype": "Customer",
						"customer_name": name,
						"customer_group": groups["customer_groups"].get(segment) or _root("Customer Group"),
						"territory": random.choice(groups["territories"]),
						"customer_type": "Individual" if segment.endswith("walk_in") else "Company",
						"payment_terms": terms.get(term_key),
					},
					capability=CUSTOMERS,
					logical_id=f"customer:{index:04d}",
				)

				self._attach_address_and_contact(
					context, doc.doctype, doc.name, name, random, primary, options
				)

				customers.append(
					{
						"name": doc.name,
						"segment": segment,
						"payment_terms": terms.get(term_key),
						"term_key": term_key,
						"credit_days": _credit_days(term_key),
						"pays_cash": term_key == "cash",
					}
				)
				context.progress(f"Created customer {doc.name}.", current=index, total=count)

		return customers

	# -- suppliers -----------------------------------------------------------
	def _create_suppliers(self, context: ScenarioContext, groups: dict[str, Any]) -> list[dict[str, Any]]:
		context.current_capability = SUPPLIERS
		parties = context.section("parties")
		options = self.options(context)
		random = context.random("suppliers")
		primary = context.faker("suppliers", context.locale)
		secondary = context.faker("suppliers_secondary", context.secondary_locale)
		terms = context.require(PAYMENT_TERMS)

		count = int(parties.get("suppliers") or 0)
		taken: set[str] = set()
		suppliers: list[dict[str, Any]] = []

		for index in range(1, count + 1):
			base = party_name(
				random, primary, secondary, primary_share=float(options.get("primary_locale_share", 0.6))
			)
			name = unique_name(base, taken)
			while frappe.db.exists("Supplier", name):
				name = unique_name(base, taken)

			term_key = random.weighted_key({"net_30": 3.0, "net_60": 2.0, "cash": 1.0})
			doc = context.insert(
				{
					"doctype": "Supplier",
					"supplier_name": name,
					"supplier_group": groups["supplier_group"],
					"supplier_type": "Company",
					"country": context.country_pack.country,
					"payment_terms": terms.get(term_key),
				},
				capability=SUPPLIERS,
				logical_id=f"supplier:{index:04d}",
			)

			self._attach_address_and_contact(context, doc.doctype, doc.name, name, random, primary, options)

			suppliers.append(
				{
					"name": doc.name,
					"term_key": term_key,
					"credit_days": _credit_days(term_key),
					# A supplier that is consistently slower or faster than its family's
					# nominal lead time makes purchasing data look real.
					"lead_time_bias": random.randint(-5, 15),
				}
			)
			context.progress(f"Created supplier {doc.name}.", current=index, total=count)

		return suppliers

	# -- leads ---------------------------------------------------------------
	def _create_leads(self, context: ScenarioContext, groups: dict[str, Any]) -> list[str]:
		context.current_capability = LEADS
		count = int(context.section("parties").get("leads") or 0)
		if not count:
			return []

		random = context.random("leads")
		primary = context.faker("leads", context.locale)
		secondary = context.faker("leads_secondary", context.secondary_locale)
		pack = context.country_pack

		leads: list[str] = []
		for index in range(1, count + 1):
			organisation = party_name(random, primary, secondary)
			first, last = person_name(primary)
			doc = context.insert(
				{
					"doctype": "Lead",
					"lead_name": f"{first} {last}",
					"first_name": first,
					"last_name": last,
					"company_name": organisation,
					"status": "Lead",
					"territory": random.choice(groups["territories"]),
					"email_id": pack.email_address(f"{first}.{last}", organisation),
					"mobile_no": pack.phone_number(random),
					"country": pack.country,
				},
				capability=LEADS,
				logical_id=f"lead:{index:04d}",
			)
			leads.append(doc.name)
		return leads

	# -- shared --------------------------------------------------------------
	def _attach_address_and_contact(
		self,
		context: ScenarioContext,
		link_doctype: str,
		link_name: str,
		display_name: str,
		random: Any,
		faker: Any,
		options: dict[str, Any],
	) -> None:
		pack = context.country_pack

		if options.get("create_addresses", True):
			address = pack.address(random, faker)
			context.insert(
				{
					"doctype": "Address",
					"address_title": display_name[:100],
					"address_type": "Billing",
					"is_primary_address": 1,
					"is_shipping_address": 1,
					"phone": pack.phone_number(random),
					"email_id": pack.email_address("accounts", display_name),
					"links": [{"link_doctype": link_doctype, "link_name": link_name}],
					**{key: value for key, value in address.items() if value},
				},
				capability=context.current_capability,
				dependencies=[f"{link_doctype}/{link_name}"],
			)

		if options.get("create_contacts", True):
			first, last = person_name(faker)
			context.insert(
				{
					"doctype": "Contact",
					"first_name": first,
					"last_name": last,
					"is_primary_contact": 1,
					"email_ids": [
						{
							"email_id": pack.email_address(f"{first}.{last}", display_name),
							"is_primary": 1,
						}
					],
					"phone_nos": [{"phone": pack.phone_number(random), "is_primary_mobile_no": 1}],
					"links": [{"link_doctype": link_doctype, "link_name": link_name}],
				},
				capability=context.current_capability,
				dependencies=[f"{link_doctype}/{link_name}"],
			)

	# -- validation ----------------------------------------------------------
	def validate(self, context: ScenarioContext) -> ValidationResult:
		result = ValidationResult()
		parties = context.section("parties")

		customers = context.optional(CUSTOMERS) or []
		expected_customers = int(parties.get("customers") or 0)
		if len(customers) != expected_customers:
			result.error(
				rule="erpnext.parties.customer_count",
				message=f"Expected {expected_customers} customers but the run created {len(customers)}.",
				provider=self.id,
				capability=CUSTOMERS,
				observed=len(customers),
				expected=expected_customers,
			)

		suppliers = context.optional(SUPPLIERS) or []
		expected_suppliers = int(parties.get("suppliers") or 0)
		if len(suppliers) != expected_suppliers:
			result.error(
				rule="erpnext.parties.supplier_count",
				message=f"Expected {expected_suppliers} suppliers but the run created {len(suppliers)}.",
				provider=self.id,
				capability=SUPPLIERS,
				observed=len(suppliers),
				expected=expected_suppliers,
			)

		for customer in customers:
			if customer["segment"] in CREDIT_SEGMENTS and customer["pays_cash"]:
				result.warning(
					rule="erpnext.parties.credit_terms",
					message=(
						f"{customer['name']} is in credit segment {customer['segment']} but was "
						"given cash terms."
					),
					provider=self.id,
					capability=CUSTOMERS,
					doctype="Customer",
					record=customer["name"],
				)
		return result


def _credit_days(term_key: str) -> int:
	from frappe_scenario.providers.erpnext_foundation import CREDIT_DAYS

	return CREDIT_DAYS.get(term_key, 0)


def _titleise(key: str) -> str:
	return " ".join(word.capitalize() for word in key.split("_"))


def _root(doctype: str) -> str:
	"""The nested-set root a new master should hang from."""
	matches = frappe.get_all(
		doctype,
		filters={"is_group": 1},
		pluck="name",
		order_by="lft asc",
		limit=1,
	)
	return matches[0] if matches else ""
