# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.model.document import Document


class ScenarioLabCase(Document):
	def validate(self) -> None:
		for fieldname in ("diagnosis_choices", "hints", "evidence", "injected_changes", "created_records"):
			try:
				json.loads(self.get(fieldname) or "[]")
			except ValueError:
				frappe.throw(_("{0} must contain valid JSON.").format(self.meta.get_label(fieldname)))
