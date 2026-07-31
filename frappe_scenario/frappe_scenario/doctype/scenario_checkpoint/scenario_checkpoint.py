# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.model.document import Document


class ScenarioCheckpoint(Document):
	def validate(self) -> None:
		try:
			payload = json.loads(self.snapshot_json or "{}")
		except ValueError as exception:
			frappe.throw(_("Checkpoint snapshot is not valid JSON: {0}").format(exception))
		if payload.get("run") != self.scenario_run or not isinstance(payload.get("records"), dict):
			frappe.throw(_("Checkpoint snapshot does not match its Scenario Run."))

	def on_trash(self) -> None:
		if self.checkpoint_type == "Baseline" and frappe.db.exists("Scenario Run", self.scenario_run):
			run_status = frappe.db.get_value("Scenario Run", self.scenario_run, "status")
			if run_status == "Completed":
				frappe.throw(_("The generated baseline cannot be deleted while its Scenario Run is active."))
