# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Document-level integrity validators.

These read the manifest rather than the ledger, so they also cover masters and
any DocType a third-party provider contributed.
"""

from __future__ import annotations

from collections import defaultdict

import frappe

from frappe_scenario.core.context import ScenarioContext
from frappe_scenario.core.validation import ValidationResult
from frappe_scenario.validators.ledger import REPORT_LIMIT


def validate_no_open_drafts(context: ScenarioContext) -> ValidationResult:
	"""A finished scenario should not leave submittable documents in draft."""
	result = ValidationResult()
	for doctype, names in _created_by_doctype(context).items():
		if not _is_submittable(doctype):
			continue
		drafts = frappe.get_all(
			doctype, filters={"name": ("in", names), "docstatus": 0}, pluck="name", limit=REPORT_LIMIT + 1
		)
		for name in drafts[:REPORT_LIMIT]:
			result.warning(
				rule="documents.no_open_drafts",
				message=f"{doctype} {name} is still a draft.",
				doctype=doctype,
				record=name,
				remediation="Submit the document or exclude it from the scenario.",
			)
		if len(drafts) > REPORT_LIMIT:
			result.warning(
				rule="documents.no_open_drafts",
				message=f"Further {doctype} drafts remain beyond the first {REPORT_LIMIT}.",
				doctype=doctype,
			)
	return result


def validate_manifest_records_exist(context: ScenarioContext) -> ValidationResult:
	"""Every manifest record must still be present, or cleanup cannot be trusted."""
	result = ValidationResult()
	for doctype, names in _created_by_doctype(context).items():
		if not frappe.db.exists("DocType", doctype):
			result.error(
				rule="documents.manifest_intact",
				message=f"The manifest references {doctype}, which no longer exists on this site.",
				doctype=doctype,
			)
			continue

		present = set(frappe.get_all(doctype, filters={"name": ("in", names)}, pluck="name"))
		missing = sorted(set(names) - present)
		for name in missing[:REPORT_LIMIT]:
			result.error(
				rule="documents.manifest_intact",
				message=f"{doctype} {name} was recorded by the scenario but no longer exists.",
				doctype=doctype,
				record=name,
				remediation="Re-run the scenario; cleanup can no longer remove this record.",
			)
		if len(missing) > REPORT_LIMIT:
			result.error(
				rule="documents.manifest_intact",
				message=f"{len(missing) - REPORT_LIMIT} further {doctype} records are missing.",
				doctype=doctype,
				observed=len(missing),
			)
	return result


def _created_by_doctype(context: ScenarioContext) -> dict[str, list[str]]:
	grouped: dict[str, set[str]] = defaultdict(set)
	for record in context.manifest.created():
		grouped[record.doctype].add(record.name)
	return {doctype: sorted(names) for doctype, names in grouped.items()}


def _is_submittable(doctype: str) -> bool:
	try:
		return bool(frappe.get_meta(doctype).is_submittable)
	except frappe.DoesNotExistError:
		return False
