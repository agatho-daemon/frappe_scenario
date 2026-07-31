# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""OpenAI Responses API adapter.

This module builds request descriptions only. Network execution is introduced
with the approved AI Brief workflow, not through this adapter contract.
"""

from __future__ import annotations

import json
from typing import Any

from frappe_scenario.ai.base import (
	AIAdapter,
	AICapability,
	AIConfigurationStatus,
	AIRequest,
)

DEFAULT_ENDPOINT = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5.6-sol"


class OpenAIAdapter(AIAdapter):
	id = "openai"
	title = "OpenAI"
	version = "1.0.0"
	default_model = DEFAULT_MODEL
	capabilities = frozenset(AICapability)

	def validate_configuration(
		self, *, configured: bool, configuration: dict[str, Any]
	) -> AIConfigurationStatus:
		endpoint = str(configuration.get("base_url") or DEFAULT_ENDPOINT)
		messages: list[str] = []
		if not endpoint.startswith("https://"):
			messages.append("The OpenAI endpoint must use HTTPS.")
		if not configured:
			messages.append("An encrypted OpenAI API credential is required.")
		return AIConfigurationStatus(
			valid=not messages,
			configured=configured,
			messages=tuple(messages),
		)

	def build_request(
		self,
		*,
		operation: AICapability,
		instructions: str,
		input_data: dict[str, Any],
		output_schema: dict[str, Any],
		model: str | None = None,
		configuration: dict[str, Any] | None = None,
	) -> AIRequest:
		if operation not in self.capabilities:
			raise ValueError(f"OpenAI does not support {operation!s}.")
		configuration = configuration or {}
		endpoint = str(configuration.get("base_url") or DEFAULT_ENDPOINT)
		selected_model = model or str(configuration.get("model") or self.default_model)
		return AIRequest(
			provider=self.id,
			operation=operation,
			model=selected_model,
			endpoint=endpoint,
			headers={"Content-Type": "application/json"},
			body={
				"model": selected_model,
				"instructions": instructions,
				"input": [
					{
						"role": "user",
						"content": [
							{
								"type": "input_text",
								"text": json.dumps(input_data, sort_keys=True),
							}
						],
					}
				],
				"text": {
					"format": {
						"type": "json_schema",
						"name": f"frappe_scenario_{operation.value}",
						"strict": True,
						"schema": output_schema,
					}
				},
			},
		)
