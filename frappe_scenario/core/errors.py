# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Structured error types.

Every failure raised inside the scenario platform carries enough structure for a
CLI, an HTTP client, or an external agent to act on it without parsing prose.
"""

from __future__ import annotations

from typing import Any


class ScenarioError(Exception):
	"""Base class for every structured scenario failure."""

	code = "scenario_error"

	def __init__(
		self,
		message: str,
		*,
		provider: str | None = None,
		capability: str | None = None,
		phase: str | None = None,
		record: str | None = None,
		details: dict[str, Any] | None = None,
	):
		super().__init__(message)
		self.message = message
		self.provider = provider
		self.capability = capability
		self.phase = phase
		self.record = record
		self.details = details or {}

	def as_dict(self) -> dict[str, Any]:
		return {
			"code": self.code,
			"message": self.message,
			"provider": self.provider,
			"capability": self.capability,
			"phase": self.phase,
			"record": self.record,
			"details": self.details,
		}

	def __str__(self) -> str:  # pragma: no cover - representation only
		parts = [self.message]
		context = {
			"provider": self.provider,
			"capability": self.capability,
			"phase": self.phase,
			"record": self.record,
		}
		suffix = ", ".join(f"{key}={value}" for key, value in context.items() if value)
		if suffix:
			parts.append(f"({suffix})")
		return " ".join(parts)


class SpecificationError(ScenarioError):
	"""The supplied specification is not schema valid or not internally coherent."""

	code = "specification_error"


class DiscoveryError(ScenarioError):
	"""A provider could not be discovered, imported, or registered."""

	code = "discovery_error"


class DependencyError(ScenarioError):
	"""Capabilities are missing, duplicated, or form a cycle."""

	code = "dependency_error"


class SafetyError(ScenarioError):
	"""The target site is not an approved scenario target."""

	code = "safety_error"


class ProviderError(ScenarioError):
	"""A provider failed during plan, generate, validate, or cleanup."""

	code = "provider_error"


class CleanupBlockedError(ScenarioError):
	"""Cleanup cannot continue because external records depend on generated data."""

	code = "cleanup_blocked"


class CompatibilityError(ScenarioError):
	"""The installed framework or app version cannot satisfy a required behaviour."""

	code = "compatibility_error"
