# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.model.document import Document


class ScenarioLearningPath(Document):
	def validate(self) -> None:
		try:
			json.loads(self.lesson_definition or "[]")
		except ValueError as exception:
			frappe.throw(f"Lesson Definition must be valid JSON: {exception}")
