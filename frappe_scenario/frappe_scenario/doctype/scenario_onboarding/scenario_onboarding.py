# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Scenario Onboarding singleton controller."""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.model.document import Document

from frappe_scenario.core.onboarding import (
	NEEDS_PREREQUISITES,
	json_fields,
	validate_transition,
)


class ScenarioOnboarding(Document):
	def validate(self) -> None:
		self._validate_json_fields()
		previous = self.get_doc_before_save()
		validate_transition(
			previous.status if previous else NEEDS_PREREQUISITES,
			self.status or NEEDS_PREREQUISITES,
		)

	def _validate_json_fields(self) -> None:
		for fieldname in json_fields():
			value = self.get(fieldname)
			if not value:
				continue
			try:
				json.loads(value)
			except (TypeError, ValueError):
				frappe.throw(
					_("{0} must contain valid JSON.").format(self.meta.get_label(fieldname)),
					frappe.ValidationError,
				)
