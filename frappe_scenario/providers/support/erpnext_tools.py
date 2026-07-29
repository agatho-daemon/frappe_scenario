# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""ERPNext lookup helpers.

Small, defensive readers over ERPNext masters. They exist so providers can ask
"which account is the company's stock-in-hand?" without hard-coding an account
name that differs between chart of accounts templates or ERPNext versions.

Nothing here writes; writers live in the providers so that every insert passes
through :meth:`ScenarioContext.insert` and lands in the manifest.
"""

from __future__ import annotations

from typing import Any

import frappe


def company_abbr(company: str) -> str:
	return frappe.db.get_value("Company", company, "abbr") or ""


def find_account(
	company: str,
	*,
	account_name: str | None = None,
	account_names: list[str] | None = None,
	account_type: str | None = None,
	root_type: str | None = None,
	is_group: int = 0,
) -> str | None:
	"""First matching non-group account, preferring the earliest name given."""
	names = account_names or ([account_name] if account_name else [])
	for candidate in names:
		match = frappe.db.get_value(
			"Account",
			{"company": company, "account_name": candidate, "is_group": is_group},
			"name",
		)
		if match:
			return match

	filters: dict[str, Any] = {"company": company, "is_group": is_group}
	if account_type:
		filters["account_type"] = account_type
	if root_type:
		filters["root_type"] = root_type
	if account_type or root_type:
		matches = frappe.get_all("Account", filters=filters, pluck="name", order_by="name asc", limit=1)
		if matches:
			return matches[0]
	return None


def account_group(company: str, *, account_name: str, root_type: str | None = None) -> str | None:
	"""A group account to parent new accounts under."""
	match = frappe.db.get_value(
		"Account", {"company": company, "account_name": account_name, "is_group": 1}, "name"
	)
	if match:
		return match
	if root_type:
		matches = frappe.get_all(
			"Account",
			filters={"company": company, "root_type": root_type, "is_group": 1},
			pluck="name",
			order_by="lft asc",
			limit=1,
		)
		if matches:
			return matches[0]
	return None


def default_warehouse(company: str) -> str | None:
	abbr = company_abbr(company)
	for candidate in (f"Stores - {abbr}", f"Finished Goods - {abbr}", f"All Warehouses - {abbr}"):
		if frappe.db.exists("Warehouse", candidate):
			if not frappe.db.get_value("Warehouse", candidate, "is_group"):
				return candidate
	matches = frappe.get_all(
		"Warehouse",
		filters={"company": company, "is_group": 0},
		pluck="name",
		order_by="creation asc",
		limit=1,
	)
	return matches[0] if matches else None


def warehouse_root(company: str) -> str | None:
	matches = frappe.get_all(
		"Warehouse",
		filters={"company": company, "is_group": 1},
		pluck="name",
		order_by="lft asc",
		limit=1,
	)
	return matches[0] if matches else None


def default_cost_center(company: str) -> str | None:
	return frappe.db.get_value("Company", company, "cost_center") or frappe.db.get_value(
		"Cost Center", {"company": company, "is_group": 0}, "name"
	)


def fiscal_year_for(date: Any, company: str | None = None) -> str | None:
	from erpnext.accounts.utils import get_fiscal_year

	try:
		return get_fiscal_year(date, company=company, as_dict=False)[0]
	except Exception:
		return None


def price_list(name: str, buying: bool) -> str | None:
	if frappe.db.exists("Price List", name):
		return name
	matches = frappe.get_all(
		"Price List",
		filters={"buying": 1 if buying else 0, "selling": 0 if buying else 1, "enabled": 1},
		pluck="name",
		order_by="creation asc",
		limit=1,
	)
	return matches[0] if matches else None


def has_field(doctype: str, fieldname: str) -> bool:
	try:
		return bool(frappe.get_meta(doctype).has_field(fieldname))
	except Exception:
		return False


def set_if_supported(doc: Any, fieldname: str, value: Any) -> None:
	"""Set a field only when this ERPNext version actually has it."""
	if has_field(doc.doctype, fieldname):
		doc.set(fieldname, value)


def outstanding_invoices(company: str, doctype: str, names: list[str]) -> list[dict[str, Any]]:
	if not names:
		return []
	return frappe.get_all(
		doctype,
		filters={"name": ("in", names), "company": company, "docstatus": 1},
		fields=["name", "outstanding_amount", "grand_total", "posting_date", "currency"],
		order_by="posting_date asc, name asc",
	)
