# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class ScenarioTutorExchange(Document):
	def validate(self):
		before = self.get_doc_before_save()
		if not before:
			return
		immutable = (
			"scenario_run",
			"question",
			"answer",
			"claims",
			"citations",
			"proposed_corrections",
			"evidence_hash",
			"evidence_bundle",
			"provider",
			"model",
			"adapter_version",
			"prompt_version",
			"provider_response_id",
			"provider_usage",
		)
		if any(before.get(fieldname) != self.get(fieldname) for fieldname in immutable):
			frappe.throw(_("Tutor evidence and answers are immutable."))
		allowed = {
			"Answered": {"Answered"},
			"Correction Proposed": {"Correction Proposed", "Correction Confirmed"},
			"Correction Confirmed": {"Correction Confirmed"},
		}
		if self.status not in allowed.get(before.status, {before.status}):
			frappe.throw(_("Invalid tutor exchange status transition."))
		if self.status == "Correction Confirmed" and before.status != "Correction Confirmed":
			if not self.confirmed_by or not self.confirmed_on:
				frappe.throw(_("Corrective suggestions require explicit human confirmation."))
