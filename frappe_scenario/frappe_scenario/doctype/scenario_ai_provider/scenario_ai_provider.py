# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe.model.document import Document

from frappe_scenario.ai.configuration import parse_public_configuration
from frappe_scenario.ai.registry import discover_ai_adapters


class ScenarioAIProvider(Document):
	def validate(self):
		adapter = discover_ai_adapters().get(self.provider)
		configuration = parse_public_configuration(self.configuration)
		if self.model:
			configuration["model"] = self.model
		# Credential absence is allowed while saving initial configuration. It is
		# reported as not ready by discovery and enforced before any model call.
		configured = bool(self.get_password("credential", raise_exception=False))
		status = adapter.validate_configuration(
			configured=configured,
			configuration=configuration,
		)
		endpoint_errors = [message for message in status.messages if "endpoint" in message.lower()]
		if endpoint_errors:
			frappe.throw(" ".join(endpoint_errors))
