# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Scenario Definition.

A named, reusable specification. Saving it validates the document against the
scenario JSON schema, so a broken specification is caught at authoring time
rather than halfway through a generation run.
"""

import json

import frappe
from frappe import _
from frappe.model.document import Document

from frappe_scenario.core.errors import ScenarioError
from frappe_scenario.core.specification import SCHEMA_VERSION, load_specification, validate_schema


class ScenarioDefinition(Document):
	def validate(self) -> None:
		specification = self._parsed_specification()
		validate_schema(specification)
		self._fill_summary(specification)

	def _parsed_specification(self) -> dict:
		try:
			specification = load_specification(self.specification)
		except ScenarioError as exception:
			frappe.throw(_(str(exception)), title=_("Invalid Specification"))
		except ValueError as exception:
			frappe.throw(_("Specification is not valid JSON or YAML: {0}").format(exception))
		return specification

	def _fill_summary(self, specification: dict) -> None:
		scenario = specification.get("scenario") or {}
		self.schema_version = specification.get("schema_version") or SCHEMA_VERSION
		self.archetype = scenario.get("archetype")
		self.country = scenario.get("country")
		self.scale = scenario.get("scale")
		self.seed = scenario.get("seed")
		self.anchor_date = scenario.get("anchor_date")
		# Store the canonical form so diffs between definitions are meaningful.
		self.specification = json.dumps(specification, indent="\t", sort_keys=True)
