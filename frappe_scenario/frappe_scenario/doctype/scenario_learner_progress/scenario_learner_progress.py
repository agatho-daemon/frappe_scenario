# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.model.document import Document


class ScenarioLearnerProgress(Document):
	def validate(self) -> None:
		try:
			completed = json.loads(self.completed_steps or "[]")
		except ValueError as exception:
			frappe.throw(f"Completed Steps must be valid JSON: {exception}")
		if not isinstance(completed, list) or not all(isinstance(step, str) for step in completed):
			frappe.throw("Completed Steps must be a JSON list of step identifiers.")
		try:
			versions = json.loads(self.lesson_versions or "{}")
		except ValueError as exception:
			frappe.throw(f"Lesson Versions must be valid JSON: {exception}")
		if not isinstance(versions, dict) or not all(
			isinstance(key, str) and isinstance(value, str) for key, value in versions.items()
		):
			frappe.throw("Lesson Versions must be a JSON object of lesson keys and versions.")
		existing = frappe.db.get_value(
			self.doctype,
			{
				"scenario_run": self.scenario_run,
				"path_key": self.path_key,
				"path_version": self.path_version,
				"user": self.user,
				"name": ["!=", self.name or ""],
			},
			"name",
		)
		if existing:
			frappe.throw("A learner can have only one progress record per scenario learning path.")
