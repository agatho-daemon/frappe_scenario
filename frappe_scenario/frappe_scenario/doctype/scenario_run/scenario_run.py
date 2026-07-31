# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Scenario Run.

The controller is deliberately thin. Everything that generates, validates, or
cleans up lives in :mod:`frappe_scenario.core.engine` so that the CLI, the API,
and the desk all drive exactly the same code path.
"""

import json

import frappe
from frappe import _
from frappe.model.document import Document


class ScenarioRun(Document):
	def validate(self) -> None:
		self._require_valid_json()
		self._protect_approved_specification()

	def on_trash(self) -> None:
		if self.status == "Completed":
			frappe.throw(
				_(
					"Delete the generated data with Cleanup before deleting this run, "
					"otherwise its records can no longer be traced."
				)
			)
		frappe.db.delete("Scenario Validation Result", {"scenario_run": self.name})
		frappe.db.delete("Scenario Event", {"scenario_run": self.name})
		frappe.db.delete("Scenario Quality Report", {"scenario_run": self.name})
		frappe.db.delete("Scenario Learner Progress", {"scenario_run": self.name})
		frappe.db.delete("Scenario Checkpoint", {"scenario_run": self.name})
		frappe.db.delete("Scenario Lab Case", {"scenario_run": self.name})

	def _require_valid_json(self) -> None:
		for fieldname in ("specification", "plan_json", "assumptions", "compatibility"):
			value = self.get(fieldname)
			if not value:
				continue
			try:
				json.loads(value)
			except ValueError as exception:
				frappe.throw(
					_("{0} is not valid JSON: {1}").format(_(self.meta.get_label(fieldname)), exception)
				)

	def _protect_approved_specification(self) -> None:
		"""An approved specification is what was reviewed; it must not drift."""
		if self.is_new() or not self.approved:
			return
		before = self.get_doc_before_save()
		if before and before.approved and before.specification != self.specification:
			frappe.throw(
				_("The specification of an approved run cannot be changed. Create a new run instead.")
			)
