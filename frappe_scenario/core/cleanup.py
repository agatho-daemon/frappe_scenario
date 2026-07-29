# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Cleanup.

Cleanup only ever touches records listed in the run manifest, in reverse
dependency order:

1. cancel submitted transactions (newest first);
2. delete created documents (newest first), deferring anything still linked
   from another manifest record;
3. restore recorded changes to pre-existing records.

If a record is linked from something *outside* the manifest, cleanup stops for
that record and reports a structured blocker rather than forcing the delete.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import frappe

from frappe_scenario.core.manifest import ManifestRecord
from frappe_scenario.core.provider import CleanupResult

ProgressCallback = Callable[[str, int, int], None]

#: Cancelling these cascades to their own dependents, so they must go first.
_CANCEL_PRIORITY = {
	"Payment Entry": 0,
	"Journal Entry": 1,
	"Sales Invoice": 2,
	"Purchase Invoice": 3,
	"Delivery Note": 4,
	"Purchase Receipt": 5,
	"Stock Entry": 6,
	"Stock Reconciliation": 7,
	"Sales Order": 8,
	"Purchase Order": 9,
}


def _linked_documents(doctype: str, name: str) -> list[dict[str, str]]:
	"""Return documents linking to this record, using Frappe's own link resolver."""
	from frappe.desk.form.linked_with import get_linked_docs, get_linked_doctypes

	links: list[dict[str, str]] = []
	try:
		linkinfo = get_linked_doctypes(doctype)
		linked = get_linked_docs(doctype, name, linkinfo)
	except Exception:
		return links

	for linked_doctype, documents in (linked or {}).items():
		for document in documents or []:
			linked_name = document.get("name") if isinstance(document, dict) else document
			if not linked_name:
				continue
			links.append(
				{
					"doctype": linked_doctype,
					"name": str(linked_name),
					"fieldname": str((linkinfo.get(linked_doctype) or {}).get("fieldname") or ""),
				}
			)
	return links


def _external_blockers(
	record: ManifestRecord,
	owned: set[tuple[str, str]],
	exception: Exception,
) -> list[dict[str, Any]]:
	blockers: list[dict[str, Any]] = []
	for link in _linked_documents(record.doctype, record.name):
		if (link["doctype"], link["name"]) in owned:
			continue
		blockers.append(
			{
				"doctype": record.doctype,
				"name": record.name,
				"linked_doctype": link["doctype"],
				"linked_name": link["name"],
				"fieldname": link["fieldname"],
				"message": (
					f"{record.doctype} {record.name} is linked from {link['doctype']} "
					f"{link['name']}, which this run does not own."
				),
			}
		)
	if not blockers:
		blockers.append(
			{
				"doctype": record.doctype,
				"name": record.name,
				"message": f"Could not delete {record.doctype} {record.name}: {exception}",
			}
		)
	return blockers


def _cancel(records: list[ManifestRecord], result: CleanupResult) -> None:
	submitted = [record for record in records if record.docstatus == 1 and record.operation == "created"]
	submitted.sort(
		key=lambda record: (_CANCEL_PRIORITY.get(record.doctype, 50), -record.sequence),
	)
	for record in submitted:
		if not frappe.db.exists(record.doctype, record.name):
			continue
		try:
			doc = frappe.get_doc(record.doctype, record.name)
			if doc.docstatus == 1:
				doc.flags.ignore_permissions = True
				doc.cancel()
				result.cancelled += 1
		except Exception as exception:
			result.blockers.append(
				{
					"doctype": record.doctype,
					"name": record.name,
					"phase": "cancel",
					"message": f"Could not cancel {record.doctype} {record.name}: {exception}",
				}
			)


def _delete(records: list[ManifestRecord], result: CleanupResult) -> None:
	created = [record for record in records if record.operation == "created"]
	owned = {(record.doctype, record.name) for record in created}
	pending = sorted(created, key=lambda record: -record.sequence)

	# Deferral loop: a record still linked from another owned record is retried
	# after that record is gone. Progress is required each pass or we stop.
	while pending:
		deferred: list[ManifestRecord] = []
		blocked: list[ManifestRecord] = []
		for record in pending:
			if not frappe.db.exists(record.doctype, record.name):
				continue
			try:
				frappe.delete_doc(
					record.doctype,
					record.name,
					ignore_permissions=True,
					delete_permanently=True,
				)
				result.deleted += 1
			except frappe.LinkExistsError as exception:
				blockers = _external_blockers(record, owned, exception)
				external = [item for item in blockers if item.get("linked_doctype")]
				if external:
					blocked.append(record)
					result.blockers.extend(external)
				else:
					deferred.append(record)
			except Exception as exception:
				deferred.append(record)
				result.warnings.append(f"Deferred {record.doctype} {record.name}: {exception}")

		if len(deferred) == len(pending):
			for record in deferred:
				result.blockers.append(
					{
						"doctype": record.doctype,
						"name": record.name,
						"phase": "delete",
						"message": (
							f"Cleanup could not make progress on {record.doctype} {record.name}. "
							"It is still referenced."
						),
					}
				)
			return
		pending = deferred


def _restore(records: list[ManifestRecord], result: CleanupResult) -> None:
	for record in sorted(
		(item for item in records if item.operation == "modified"),
		key=lambda item: -item.sequence,
	):
		if not record.original_values:
			continue

		is_single = bool(frappe.get_meta(record.doctype).issingle)
		if not is_single and not frappe.db.exists(record.doctype, record.name):
			result.warnings.append(
				f"Cannot restore {record.doctype} {record.name}: the record no longer exists."
			)
			continue
		try:
			for fieldname, value in record.original_values.items():
				if is_single:
					frappe.db.set_single_value(record.doctype, fieldname, value)
				else:
					frappe.db.set_value(record.doctype, record.name, fieldname, value, update_modified=False)
			if is_single:
				frappe.clear_document_cache(record.doctype, record.name)
			result.restored += 1
		except Exception as exception:
			result.blockers.append(
				{
					"doctype": record.doctype,
					"name": record.name,
					"phase": "restore",
					"message": f"Could not restore original values: {exception}",
				}
			)


def default_cleanup(provider_id: str, records: list[ManifestRecord]) -> CleanupResult:
	"""Generic reverse-dependency cleanup used unless a provider overrides it."""
	result = CleanupResult(provider=provider_id)
	if not records:
		return result

	_cancel(records, result)
	# Cancelling a stock or accounting document queues an item valuation repost.
	# ERPNext then refuses to cancel anything else until that repost has run, and
	# it also refuses to delete a document whose repost is still outstanding.
	# There is no background worker behind a scenario run, so settle the queue here.
	_flush_deferred_work(result)
	_delete(records, result)
	_restore(records, result)
	return result


def _flush_deferred_work(result: CleanupResult) -> None:
	from frappe_scenario.compatibility import get_adapter

	try:
		get_adapter().flush_deferred_work()
	except Exception as exception:
		result.blockers.append(
			{
				"phase": "cleanup",
				"message": f"Could not settle deferred item valuation reposts: {exception}",
			}
		)
