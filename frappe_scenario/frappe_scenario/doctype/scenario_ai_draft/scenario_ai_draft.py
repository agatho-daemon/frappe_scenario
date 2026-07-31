# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""A reviewable, provenance-preserving AI or external-agent compilation."""

import hashlib
import json

import frappe
from frappe import _
from frappe.model.document import Document

from frappe_scenario.core.errors import ScenarioError
from frappe_scenario.core.specification import (
	SCHEMA_VERSION,
	load_specification,
	problems_as_html,
	validate_schema,
)


class ScenarioAIDraft(Document):
	def validate(self) -> None:
		self.input_hash = _digest({"brief": self.brief, "constraints": _parse(self.constraints)})
		self._validate_compiled_specification()
		self._retain_model_output_hash()
		self._track_human_edit()
		self._stamp_approval()

	def _retain_model_output_hash(self) -> None:
		if self.model_output and not self.model_output_hash:
			try:
				self.model_output_hash = _digest(json.loads(self.model_output))
			except ValueError:
				frappe.throw(_("Model output must be valid JSON."))

	def _validate_compiled_specification(self) -> None:
		if not self.compiled_specification:
			self.output_hash = None
			return

		try:
			specification = load_specification(self.compiled_specification)
		except ScenarioError as exception:
			frappe.throw(_(str(exception)), title=_("Invalid Compiled Specification"))
		except ValueError as exception:
			frappe.throw(_("Compiled specification is not valid JSON or YAML: {0}").format(exception))

		# ``validate_schema`` reports rather than raises, so an unchecked return
		# value would let an invalid draft reach approval.
		problems = validate_schema(specification)
		if problems:
			frappe.throw(problems_as_html(problems), title=_("Invalid Compiled Specification"))

		self.schema_version = specification.get("schema_version") or SCHEMA_VERSION
		self.compiled_specification = json.dumps(specification, indent="\t", sort_keys=True)
		self.output_hash = _digest(specification)

	def _track_human_edit(self) -> None:
		before = self.get_doc_before_save()
		if not before:
			return
		if before.compiled_specification and before.compiled_specification != self.compiled_specification:
			self.edited_by_human = 1

	def _stamp_approval(self) -> None:
		before = self.get_doc_before_save()
		was_approved = bool(before and before.approval_status == "Approved")
		if self.approval_status == "Approved" and not was_approved:
			if not self.compiled_specification:
				frappe.throw(_("A draft cannot be approved before it has a compiled specification."))
			self.approved_by = frappe.session.user
			self.approved_on = frappe.utils.now_datetime()
		elif self.approval_status != "Approved":
			self.approved_by = None
			self.approved_on = None


def _parse(value: str | None) -> dict:
	if not value:
		return {}
	try:
		return json.loads(value)
	except ValueError:
		frappe.throw(_("Constraints must be valid JSON."))
		return {}


def _digest(payload: dict) -> str:
	encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
	return hashlib.sha256(encoded).hexdigest()
