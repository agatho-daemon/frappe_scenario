# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""General ledger integrity validators."""

from __future__ import annotations

import datetime
from typing import Any

import frappe
from frappe.query_builder import DocType
from frappe.query_builder.functions import Sum

from frappe_scenario.core.context import ScenarioContext
from frappe_scenario.core.validation import ValidationResult
from frappe_scenario.providers.erpnext_foundation import COMPANY

#: Rounding noise below this is not a real imbalance.
TOLERANCE = 0.005

#: How many offending records to name before summarising the rest.
REPORT_LIMIT = 10


def validate_vouchers_balanced(context: ScenarioContext) -> ValidationResult:
	"""Every voucher must post equal debits and credits."""
	result = ValidationResult()
	company = context.optional(COMPANY)
	if not company:
		return result

	gl = DocType("GL Entry")
	rows = (
		frappe.qb.from_(gl)
		.select(
			gl.voucher_type,
			gl.voucher_no,
			(Sum(gl.debit) - Sum(gl.credit)).as_("difference"),
		)
		.where(gl.company == company)
		.where(gl.is_cancelled == 0)
		.groupby(gl.voucher_type, gl.voucher_no)
		.run(as_dict=True)
	)

	unbalanced = [row for row in rows if abs(float(row.difference or 0)) > TOLERANCE]
	for row in unbalanced[:REPORT_LIMIT]:
		result.error(
			rule="ledger.voucher_balanced",
			message=f"{row.voucher_type} {row.voucher_no} is out of balance by {float(row.difference):.4f}.",
			doctype=row.voucher_type,
			record=row.voucher_no,
			observed=round(float(row.difference), 4),
			expected=0,
			remediation="Inspect the voucher's GL entries; a controller or hook may have skewed it.",
		)
	if len(unbalanced) > REPORT_LIMIT:
		result.error(
			rule="ledger.voucher_balanced",
			message=f"{len(unbalanced) - REPORT_LIMIT} further vouchers are out of balance.",
			observed=len(unbalanced),
		)
	return result


def validate_trial_balance(context: ScenarioContext) -> ValidationResult:
	"""Total debits must equal total credits across the company."""
	result = ValidationResult()
	company = context.optional(COMPANY)
	if not company:
		return result

	gl = DocType("GL Entry")
	rows = (
		frappe.qb.from_(gl)
		.select(Sum(gl.debit).as_("debit"), Sum(gl.credit).as_("credit"))
		.where(gl.company == company)
		.where(gl.is_cancelled == 0)
		.run(as_dict=True)
	)
	if not rows:
		return result

	debit = float(rows[0].debit or 0)
	credit = float(rows[0].credit or 0)
	if abs(debit - credit) > TOLERANCE:
		result.error(
			rule="ledger.trial_balance",
			message=f"Trial balance is out by {debit - credit:.4f} ({debit:.2f} debit, {credit:.2f} credit).",
			doctype="Company",
			record=company,
			observed=round(debit - credit, 4),
			expected=0,
		)
	elif debit == 0:
		result.warning(
			rule="ledger.trial_balance",
			message="The company has no general ledger activity.",
			doctype="Company",
			record=company,
		)
	return result


def validate_control_accounts_have_parties(context: ScenarioContext) -> ValidationResult:
	"""Receivable and payable postings must always carry a party."""
	result = ValidationResult()
	company = context.optional(COMPANY)
	if not company:
		return result

	control_accounts = frappe.get_all(
		"Account",
		filters={"company": company, "account_type": ("in", ["Receivable", "Payable"]), "is_group": 0},
		pluck="name",
	)
	if not control_accounts:
		return result

	orphans = frappe.get_all(
		"GL Entry",
		filters={
			"company": company,
			"account": ("in", control_accounts),
			"is_cancelled": 0,
			"party": ("in", ["", None]),
		},
		fields=["name", "account", "voucher_type", "voucher_no"],
		limit=REPORT_LIMIT,
	)
	for orphan in orphans:
		result.error(
			rule="ledger.party_on_control_accounts",
			message=(
				f"{orphan.voucher_type} {orphan.voucher_no} posts to control account "
				f"{orphan.account} without a party."
			),
			doctype=orphan.voucher_type,
			record=orphan.voucher_no,
			remediation="Post overheads to a plain liability account rather than a control account.",
		)
	return result


def validate_posting_window(context: ScenarioContext) -> ValidationResult:
	"""No ledger activity may fall outside the requested history window."""
	result = ValidationResult()
	company = context.optional(COMPANY)
	if not company:
		return result

	future = frappe.get_all(
		"GL Entry",
		filters={"company": company, "is_cancelled": 0, "posting_date": (">", context.anchor_date)},
		fields=["voucher_type", "voucher_no", "posting_date"],
		limit=REPORT_LIMIT,
	)
	for entry in future:
		result.error(
			rule="ledger.posting_window",
			message=(
				f"{entry.voucher_type} {entry.voucher_no} posts on {entry.posting_date}, after the "
				f"anchor date {context.anchor_date}."
			),
			doctype=entry.voucher_type,
			record=entry.voucher_no,
			observed=str(entry.posting_date),
			expected=f"<= {context.anchor_date}",
		)

	early = frappe.get_all(
		"GL Entry",
		filters={"company": company, "is_cancelled": 0, "posting_date": ("<", context.start_date)},
		fields=["voucher_type", "voucher_no", "posting_date"],
		limit=REPORT_LIMIT,
	)
	for entry in early:
		result.warning(
			rule="ledger.posting_window",
			message=(
				f"{entry.voucher_type} {entry.voucher_no} posts on {entry.posting_date}, before the "
				f"history window opens on {context.start_date}."
			),
			doctype=entry.voucher_type,
			record=entry.voucher_no,
			observed=str(entry.posting_date),
			expected=f">= {context.start_date}",
		)
	return result


def validate_fiscal_year_coverage(context: ScenarioContext) -> ValidationResult:
	"""Every posting date must fall inside an existing fiscal year."""
	result = ValidationResult()
	company = context.optional(COMPANY)
	if not company:
		return result

	years = frappe.get_all(
		"Fiscal Year", fields=["name", "year_start_date", "year_end_date"], order_by="year_start_date asc"
	)
	if not years:
		result.error(
			rule="ledger.fiscal_year_coverage",
			message="No fiscal years exist, so nothing can be reported on.",
			doctype="Fiscal Year",
		)
		return result

	for day in (context.start_date, context.anchor_date):
		if not any(_covers(year, day) for year in years):
			result.error(
				rule="ledger.fiscal_year_coverage",
				message=f"No fiscal year covers {day}.",
				doctype="Fiscal Year",
				observed=str(day),
				remediation="Widen scenario.history_months or create the missing fiscal year.",
			)
	return result


def _covers(year: Any, day: datetime.date) -> bool:
	start = year.year_start_date
	end = year.year_end_date
	if isinstance(start, datetime.datetime):
		start = start.date()
	if isinstance(end, datetime.datetime):
		end = end.date()
	return bool(start and end and start <= day <= end)


def account_balance(company: str, account: str) -> float:
	"""Net debit balance of a ledger account."""
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
