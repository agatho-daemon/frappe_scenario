# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""The scenario provider protocol.

Providers are hybrid: declarative metadata describes what a provider requires,
provides, and costs; Python methods implement planning, generation, validation,
and cleanup.

Three roles are recognised:

``provider``  creates a foundational capability
``extender``  adds domain records using capabilities created elsewhere
``observer``  inspects resulting data without owning it
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from frappe_scenario.core.validation import ValidationResult

if TYPE_CHECKING:  # pragma: no cover - typing only
	from frappe_scenario.core.context import ScenarioContext
	from frappe_scenario.core.manifest import ManifestRecord

ProviderRole = Literal["provider", "extender", "observer"]

PROTOCOL_VERSION = "0.1"


@dataclass
class CapabilityDeclaration:
	"""Machine-readable description of one capability."""

	id: str
	description: str
	doctypes: list[str] = field(default_factory=list)
	requires: list[str] = field(default_factory=list)
	optional_requires: list[str] = field(default_factory=list)
	estimated_records: str = "unknown"
	safety: str = "Creates scenario-owned records only."
	validation_rules: list[str] = field(default_factory=list)
	incompatible_with: list[str] = field(default_factory=list)
	example: dict[str, Any] | None = None

	def as_dict(self) -> dict[str, Any]:
		return {
			"id": self.id,
			"description": self.description,
			"doctypes": list(self.doctypes),
			"requires": list(self.requires),
			"optional_requires": list(self.optional_requires),
			"estimated_records": self.estimated_records,
			"safety": self.safety,
			"validation_rules": list(self.validation_rules),
			"incompatible_with": list(self.incompatible_with),
			"example": self.example,
		}


@dataclass
class PlanStep:
	"""One read-only planned action."""

	capability: str
	description: str
	doctype: str | None = None
	estimated_records: int = 0

	def as_dict(self) -> dict[str, Any]:
		return {
			"capability": self.capability,
			"description": self.description,
			"doctype": self.doctype,
			"estimated_records": self.estimated_records,
		}


@dataclass
class ScenarioPlan:
	"""What a provider intends to do. Produced without writing anything."""

	provider: str
	steps: list[PlanStep] = field(default_factory=list)
	assumptions: list[str] = field(default_factory=list)
	unsupported: list[str] = field(default_factory=list)
	settings_changed: list[str] = field(default_factory=list)
	cleanup_notes: list[str] = field(default_factory=list)

	def step(self, capability: str, description: str, *, doctype: str | None = None, count: int = 0) -> None:
		self.steps.append(
			PlanStep(
				capability=capability,
				description=description,
				doctype=doctype,
				estimated_records=count,
			)
		)

	@property
	def estimated_records(self) -> int:
		return sum(step.estimated_records for step in self.steps)

	def as_dict(self) -> dict[str, Any]:
		return {
			"provider": self.provider,
			"steps": [step.as_dict() for step in self.steps],
			"estimated_records": self.estimated_records,
			"assumptions": list(self.assumptions),
			"unsupported": list(self.unsupported),
			"settings_changed": list(self.settings_changed),
			"cleanup_notes": list(self.cleanup_notes),
		}


@dataclass
class ProviderResult:
	"""Outcome of a generate() call."""

	provider: str
	created: int = 0
	modified: int = 0
	warnings: list[str] = field(default_factory=list)
	published: list[str] = field(default_factory=list)
	summary: dict[str, Any] = field(default_factory=dict)

	def as_dict(self) -> dict[str, Any]:
		return {
			"provider": self.provider,
			"created": self.created,
			"modified": self.modified,
			"warnings": list(self.warnings),
			"published": list(self.published),
			"summary": self.summary,
		}


@dataclass
class CleanupResult:
	"""Outcome of a cleanup() call."""

	provider: str
	cancelled: int = 0
	deleted: int = 0
	restored: int = 0
	blockers: list[dict[str, Any]] = field(default_factory=list)
	warnings: list[str] = field(default_factory=list)

	def as_dict(self) -> dict[str, Any]:
		return {
			"provider": self.provider,
			"cancelled": self.cancelled,
			"deleted": self.deleted,
			"restored": self.restored,
			"blockers": list(self.blockers),
			"warnings": list(self.warnings),
		}


class ScenarioProvider:
	"""Base class every scenario provider extends."""

	# -- declarative metadata ------------------------------------------------
	id: str = ""
	version: str = "0.0.0"
	title: str = ""
	description: str = ""
	role: ProviderRole = "provider"
	app: str = ""

	#: ``{app_name: version specifier}``; the provider is skipped when unmet.
	requires_apps: dict[str, str] = {}
	requires_capabilities: set[str] = set()
	optional_capabilities: set[str] = set()
	provides_capabilities: set[str] = set()

	#: Provider ids this one must run after even without a capability edge.
	runs_after: set[str] = set()

	#: Coarse ordering hint used to break ties deterministically.
	order: int = 100

	#: Frappe major versions this provider supports. Empty means "any".
	supported_frappe_versions: set[int] = set()

	capabilities: list[CapabilityDeclaration] = []

	# -- protocol ------------------------------------------------------------
	def get_options_schema(self) -> dict[str, Any]:
		"""Namespaced JSON Schema fragment for this provider's options."""
		return {"type": "object", "additionalProperties": True, "properties": {}}

	def plan(self, context: ScenarioContext) -> ScenarioPlan:
		raise NotImplementedError(f"{self.id} does not implement plan()")

	def generate(self, context: ScenarioContext) -> ProviderResult:
		raise NotImplementedError(f"{self.id} does not implement generate()")

	def validate(self, context: ScenarioContext) -> ValidationResult:
		return ValidationResult()

	def cleanup(self, context: ScenarioContext, records: list[ManifestRecord]) -> CleanupResult:
		"""Default cleanup is handled by the generic reverse-dependency cleaner."""
		from frappe_scenario.core.cleanup import default_cleanup

		return default_cleanup(self.id, records)

	# -- helpers -------------------------------------------------------------
	def options(self, context: ScenarioContext) -> dict[str, Any]:
		return dict((context.specification.get("providers") or {}).get(self.id) or {})

	def estimated_volume(self, context: ScenarioContext) -> int:
		return self.plan(context).estimated_records

	def describe(self) -> dict[str, Any]:
		return {
			"id": self.id,
			"version": self.version,
			"title": self.title,
			"description": self.description,
			"role": self.role,
			"app": self.app,
			"protocol_version": PROTOCOL_VERSION,
			"requires_apps": dict(self.requires_apps),
			"requires_capabilities": sorted(self.requires_capabilities),
			"optional_capabilities": sorted(self.optional_capabilities),
			"provides_capabilities": sorted(self.provides_capabilities),
			"runs_after": sorted(self.runs_after),
			"order": self.order,
			"supported_frappe_versions": sorted(self.supported_frappe_versions),
			"options_schema": self.get_options_schema(),
			"capabilities": [capability.as_dict() for capability in self.capabilities],
		}

	def __repr__(self) -> str:  # pragma: no cover - representation only
		return f"<{type(self).__name__} {self.id} v{self.version}>"
