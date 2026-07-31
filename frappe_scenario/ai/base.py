# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Stable contracts between Scenario workflows and model providers.

Adapters translate trusted Scenario inputs into provider requests. They do not
read credentials, perform HTTP requests, create documents, or execute model
output. Later workflows pass their structured requests to a separately audited
executor and validate the returned data through the normal Scenario pipeline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class AICapability(StrEnum):
	COMPILE_SPECIFICATION = "compile_specification"
	REVIEW_PLAUSIBILITY = "review_plausibility"
	EXPLAIN = "explain"
	TUTOR = "tutor"


@dataclass(frozen=True)
class AIConfigurationStatus:
	valid: bool
	configured: bool
	messages: tuple[str, ...] = ()

	def as_dict(self) -> dict[str, Any]:
		return {
			"valid": self.valid,
			"configured": self.configured,
			"messages": list(self.messages),
		}


@dataclass(frozen=True)
class AIRequest:
	"""A secret-free request description suitable for an audited executor."""

	provider: str
	operation: AICapability
	model: str
	endpoint: str
	body: dict[str, Any]
	headers: dict[str, str] = field(default_factory=dict)

	def as_dict(self) -> dict[str, Any]:
		return {
			"provider": self.provider,
			"operation": self.operation.value,
			"model": self.model,
			"endpoint": self.endpoint,
			"body": self.body,
			"headers": self.headers,
		}


class AIAdapter(ABC):
	"""Provider-neutral adapter API. Implementations must remain side-effect free."""

	id: str
	title: str
	version: str
	default_model: str
	capabilities: frozenset[AICapability]

	def describe(self) -> dict[str, Any]:
		return {
			"id": self.id,
			"title": self.title,
			"version": self.version,
			"default_model": self.default_model,
			"capabilities": sorted(capability.value for capability in self.capabilities),
		}

	@abstractmethod
	def validate_configuration(
		self, *, configured: bool, configuration: dict[str, Any]
	) -> AIConfigurationStatus:
		"""Validate non-secret configuration plus the presence of a credential."""

	@abstractmethod
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
		"""Build a secret-free structured-output request."""

	def compile_specification(self, **kwargs: Any) -> AIRequest:
		return self.build_request(operation=AICapability.COMPILE_SPECIFICATION, **kwargs)

	def review_plausibility(self, **kwargs: Any) -> AIRequest:
		return self.build_request(operation=AICapability.REVIEW_PLAUSIBILITY, **kwargs)

	def explain(self, **kwargs: Any) -> AIRequest:
		return self.build_request(operation=AICapability.EXPLAIN, **kwargs)

	def tutor(self, **kwargs: Any) -> AIRequest:
		return self.build_request(operation=AICapability.TUTOR, **kwargs)
