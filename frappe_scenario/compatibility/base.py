# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Base compatibility adapter.

The base implementation covers behaviour that is identical across every
supported branch. Version adapters override only what genuinely differs.
"""

from __future__ import annotations

import importlib
import time
from collections.abc import Callable
from typing import Any

import frappe

from frappe_scenario.core.errors import CompatibilityError


def _is_abandoned_repost(status: str | None, error_log: str | None) -> bool:
	"""Return whether ERPNext recorded a completed, recoverable worker attempt."""
	return status == "In Progress" and bool(error_log)


class CompatibilityAdapter:
	id = "base"

	#: Ordered module suffixes searched when resolving an ERPNext mapper. v15 and
	#: v16 keep mappers beside the controller; develop moved them to ``mapper``.
	mapper_module_order: tuple[str, ...] = ("{doctype_module}", "mapper")

	# -- helpers -------------------------------------------------------------
	def erpnext_mapper(self, doctype_path: str, function: str) -> Callable[..., Any]:
		"""Resolve an ERPNext document mapper across module layouts.

		``doctype_path`` is the DocType package, for example
		``erpnext.selling.doctype.sales_order``.
		"""
		doctype_module = doctype_path.rsplit(".", 1)[-1]
		attempted: list[str] = []
		for suffix in self.mapper_module_order:
			module_path = f"{doctype_path}.{suffix.format(doctype_module=doctype_module)}"
			attempted.append(f"{module_path}.{function}")
			try:
				module = importlib.import_module(module_path)
			except ImportError:
				continue
			resolved = getattr(module, function, None)
			if callable(resolved):
				return resolved

		raise CompatibilityError(
			f"Could not resolve ERPNext mapper {function!r} for {doctype_path!r}.",
			phase="compatibility",
			details={"attempted": attempted, "adapter": self.id},
		)

	def set_posting_datetime(self, doc: Any, posting_date: Any, posting_time: str = "10:00:00") -> None:
		"""Backdate a stock/accounting document through the supported flag.

		A document produced by an ERPNext mapper is dated today, and ERPNext has
		already derived its payment schedule and due date from that date. Moving
		the posting date without discarding those derived rows leaves a due date
		in the future, which ERPNext then rejects as later than the payment terms
		template allows. Clearing them lets ERPNext recompute both from the date
		we actually want.
		"""
		if doc.meta.has_field("set_posting_time"):
			doc.set_posting_time = 1
		if doc.meta.has_field("posting_date"):
			doc.posting_date = posting_date
		if doc.meta.has_field("posting_time"):
			doc.posting_time = posting_time
		if doc.meta.has_field("transaction_date"):
			doc.transaction_date = posting_date
		if doc.meta.has_field("payment_schedule"):
			doc.set("payment_schedule", [])
		if doc.meta.has_field("due_date"):
			doc.due_date = None

	def has_doctype(self, doctype: str) -> bool:
		"""Optional DocTypes differ between branches; check before using one."""
		return bool(frappe.db.exists("DocType", doctype))

	def flush_deferred_work(self) -> dict[str, Any]:
		"""Run the work ERPNext defers to a background worker.

		A backdated stock transaction does not correct the general ledger in place.
		ERPNext instead queues a Repost Item Valuation and leaves a worker to
		reconcile the stock account against the stock ledger. Almost every document
		in a generated scenario is backdated, so with no worker running the stock
		account and the stock ledger disagree and the dataset is unusable for
		reporting. Running the reposts synchronously is what makes generation
		self-contained rather than dependent on a queue being drained later.
		"""
		if not self.has_doctype("Repost Item Valuation"):
			return {"processed": [], "failed": []}

		from erpnext.stock.doctype.repost_item_valuation.repost_item_valuation import repost

		processed: list[str] = []
		seen: set[str] = set()
		failed: list[dict[str, Any]] = []
		terminal_statuses = {"Completed", "Skipped"}
		# One repost can enqueue or unblock another. Drain the bounded dependency
		# chain instead of treating an intermediate Queued state as a failure.
		for _attempt in range(10):
			pending = frappe.get_all(
				"Repost Item Valuation",
				filters={"status": ["in", ["Queued", "In Progress"]]},
				pluck="name",
				order_by="creation asc",
			)
			if not pending:
				failed = []
				break
			seen.update(pending)
			for name in pending:
				# A live Bench worker may already own an In Progress repost. Calling
				# repost concurrently would race the same stock ledger rows.
				status, error_log = frappe.db.get_value(
					"Repost Item Valuation", name, ["status", "error_log"]
				)
				# ERPNext records recoverable worker failures as In Progress together
				# with an error log. No worker still owns that attempt; put it back in
				# the synchronous drain rather than leaving the site permanently pinned.
				if _is_abandoned_repost(status, error_log):
					frappe.db.set_value(
						"Repost Item Valuation",
						name,
						{"status": "Queued", "error_log": None},
						update_modified=False,
					)
					status = "Queued"
				if status == "Queued":
					# Newer Frappe enqueues dynamic-link cleanup while the repost removes
					# its temporary attachment. This synchronous drain must not depend on
					# queue capacity or a worker, so use Frappe's own immediate test path
					# for the duration of the repost and restore the process flag exactly.
					was_in_test = frappe.in_test
					try:
						frappe.in_test = True
						repost(frappe.get_doc("Repost Item Valuation", name))
					finally:
						frappe.in_test = was_in_test
			failed = [
				{"name": name, "status": frappe.db.get_value("Repost Item Valuation", name, "status")}
				for name in pending
				if frappe.db.get_value("Repost Item Valuation", name, "status") not in terminal_statuses
			]
			if not failed:
				continue
			time.sleep(0.1)

		processed = sorted(
			name
			for name in seen
			if frappe.db.get_value("Repost Item Valuation", name, "status") in terminal_statuses
		)

		for name in processed:
			# A completed or deduplicated repost is spent bookkeeping, but it still links to the
			# company. Left in place it would block cleanup from removing the very
			# company whose backdated postings created it. It is a submittable
			# document, so it has to be cancelled before it can go.
			doc = frappe.get_doc("Repost Item Valuation", name)
			doc.flags.ignore_permissions = True
			if doc.docstatus == 1:
				doc.cancel()
			frappe.delete_doc("Repost Item Valuation", name, ignore_permissions=True, delete_permanently=True)

		if failed:
			raise CompatibilityError(
				f"{len(failed)} of {len(seen)} item valuation reposts did not complete.",
				phase="generate",
				details={"failed": failed, "adapter": self.id},
			)

		return {"processed": processed, "failed": failed}

	def has_field(self, doctype: str, fieldname: str) -> bool:
		try:
			return bool(frappe.get_meta(doctype).has_field(fieldname))
		except Exception:
			return False

	def company_creation_defaults(self) -> dict[str, Any]:
		"""Extra Company fields required for a usable scenario company."""
		return {"create_chart_of_accounts_based_on": "Standard Template"}

	def default_chart_of_accounts(self, country: str) -> str | None:
		"""Return an ERPNext chart template name for the country, if one exists."""
		try:
			from erpnext.accounts.doctype.account.chart_of_accounts.chart_of_accounts import (
				get_charts_for_country,
			)
		except ImportError:  # pragma: no cover - ERPNext not installed
			return None
		charts = get_charts_for_country(country) or []
		preferred = [chart for chart in charts if "Standard" in chart]
		return (preferred or charts or [None])[0]

	def describe(self) -> dict[str, Any]:
		return {
			"id": self.id,
			"frappe_version": getattr(frappe, "__version__", "unknown"),
			"mapper_module_order": list(self.mapper_module_order),
		}
