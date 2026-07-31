# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class ScenarioAIReview(Document):
	def validate(self):
		before = self.get_doc_before_save()
		if before:
			immutable = (
				"source_doctype",
				"source_name",
				"input_hash",
				"review_scope",
				"provider",
				"model",
				"adapter_version",
				"prompt_version",
				"catalog_hash",
				"findings",
				"approved_artifacts",
				"model_output",
				"output_hash",
			)
			if any(before.get(fieldname) != self.get(fieldname) for fieldname in immutable):
				frappe.throw(_("AI review evidence is immutable; request a new review instead."))
		if before and before.status in {"Approved", "Rejected"} and before.status != self.status:
			frappe.throw(_("A completed AI plausibility review is immutable."))
		if self.status == "Approved" and not (before and before.status == "Approved"):
			if not self.findings or not self.output_hash:
				frappe.throw(_("A review cannot be approved without validated findings."))
			from frappe_scenario.ai.plausibility import current_source_hash

			if current_source_hash() != self.input_hash:
				frappe.throw(_("The saved preview changed after this AI review. Request a new review."))
			self.approved_by = frappe.session.user
			self.approved_on = frappe.utils.now_datetime()
		elif self.status != "Approved":
			self.approved_by = None
			self.approved_on = None
