# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""The shared scenario context.

Providers receive exactly one object. It carries the resolved specification,
deterministic randomness, the capability bus, and the ownership manifest.
Providers never reach around it to touch global state.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import frappe

from frappe_scenario.core.errors import DependencyError, ProviderError
from frappe_scenario.core.manifest import Manifest, ManifestRecord
from frappe_scenario.core.random import DeterministicRandom, RandomService

ProgressCallback = Callable[[dict[str, Any]], None]


@dataclass
class ScenarioContext:
	"""Everything a provider is allowed to know about the current run."""

	run_id: str
	specification: dict[str, Any]
	manifest: Manifest = field(default_factory=Manifest)
	dry_run: bool = False

	#: Set by the engine before each provider call.
	current_provider: str = ""
	current_capability: str | None = None

	_random_service: RandomService | None = None
	_published: dict[str, Any] = field(default_factory=dict)
	_publishers: dict[str, str] = field(default_factory=dict)
	_warnings: list[dict[str, Any]] = field(default_factory=list)
	_progress_callback: ProgressCallback | None = None

	# -- construction --------------------------------------------------------
	def __post_init__(self) -> None:
		if self._random_service is None:
			self._random_service = RandomService(
				self.seed,
				locales=[self.locale, self.secondary_locale],
			)

	# -- specification accessors --------------------------------------------
	@property
	def scenario(self) -> dict[str, Any]:
		return self.specification.get("scenario") or {}

	@property
	def seed(self) -> int:
		return int(self.scenario.get("seed") or 0)

	@property
	def anchor_date(self) -> datetime.date:
		return datetime.date.fromisoformat(self.scenario["anchor_date"])

	@property
	def history_months(self) -> int:
		return int(self.scenario.get("history_months") or 1)

	@property
	def start_date(self) -> datetime.date:
		"""First day of the generated history window."""
		anchor = self.anchor_date
		months = self.history_months
		year = anchor.year
		month = anchor.month - months
		while month <= 0:
			month += 12
			year -= 1
		return datetime.date(year, month, 1)

	@property
	def scale(self) -> str:
		return str(self.scenario.get("scale") or "smoke")

	@property
	def locale(self) -> str:
		return str((self.scenario.get("locale") or {}).get("primary") or "en_US")

	@property
	def secondary_locale(self) -> str:
		return str((self.scenario.get("locale") or {}).get("secondary") or "en_US")

	@property
	def country(self) -> str:
		return str(self.scenario.get("country") or "")

	@property
	def currency(self) -> str:
		return str(self.scenario.get("currency") or "USD")

	@property
	def archetype(self) -> Any:
		from frappe_scenario.archetypes import get_archetype

		return get_archetype(self.scenario["archetype"])

	@property
	def country_pack(self) -> Any:
		from frappe_scenario.locales import get_country_pack

		return get_country_pack(self.country)

	@property
	def adapter(self) -> Any:
		from frappe_scenario.compatibility import get_adapter

		return get_adapter()

	@property
	def company(self) -> str:
		"""The scenario-owned company. Available once the company provider ran."""
		return str(self.require("erpnext.foundation.company"))

	def section(self, name: str) -> dict[str, Any]:
		return dict(self.specification.get(name) or {})

	def options(self, provider_id: str | None = None) -> dict[str, Any]:
		provider_id = provider_id or self.current_provider
		return dict((self.specification.get("providers") or {}).get(provider_id) or {})

	# -- randomness ----------------------------------------------------------
	def random(self, namespace: str = "default") -> DeterministicRandom:
		assert self._random_service is not None
		return self._random_service.random(self.current_provider or "core", namespace)

	def faker(self, namespace: str = "default", locale: str | None = None) -> Any:
		assert self._random_service is not None
		return self._random_service.faker(self.current_provider or "core", namespace, locale)

	def library_fingerprint(self) -> dict[str, Any]:
		assert self._random_service is not None
		return self._random_service.fingerprint()

	# -- capability bus ------------------------------------------------------
	def publish(self, capability: str, value: Any) -> None:
		"""Publish a capability value for downstream providers."""
		owner = self._publishers.get(capability)
		if owner and owner != self.current_provider:
			raise ProviderError(
				f"Capability {capability!r} is already published by {owner!r}.",
				provider=self.current_provider,
				capability=capability,
				phase="generate",
			)
		self._published[capability] = value
		self._publishers[capability] = self.current_provider

	def require(self, capability: str) -> Any:
		"""Fetch a published capability value or fail with a structured error."""
		if capability not in self._published:
			raise DependencyError(
				f"Capability {capability!r} is required but has not been published.",
				provider=self.current_provider,
				capability=capability,
				phase="generate",
				details={"published": sorted(self._published)},
			)
		return self._published[capability]

	def optional(self, capability: str, default: Any = None) -> Any:
		return self._published.get(capability, default)

	def restore_capabilities(self, published: dict[str, Any], *, publisher: str = "checkpoint") -> None:
		"""Reload capability values recorded at a checkpoint (resume and validate)."""
		for capability, value in published.items():
			self._published[capability] = value
			self._publishers.setdefault(capability, publisher)

	def has(self, capability: str) -> bool:
		return capability in self._published

	@property
	def published_capabilities(self) -> dict[str, Any]:
		return dict(self._published)

	def find_records(self, capability: str) -> list[ManifestRecord]:
		"""Manifest records owned by a capability."""
		return self.manifest.for_capability(capability)

	# -- ownership tracking --------------------------------------------------
	def record_created(
		self,
		doc: Any,
		*,
		capability: str | None = None,
		dependencies: list[str] | None = None,
		logical_id: str | None = None,
	) -> ManifestRecord:
		"""Record a document this run created. Must be called for every insert."""
		record = ManifestRecord(
			doctype=doc.doctype,
			name=doc.name,
			provider=self.current_provider,
			capability=capability or self.current_capability,
			operation="created",
			docstatus=int(getattr(doc, "docstatus", 0) or 0),
			dependencies=dependencies or [],
			logical_id=logical_id,
		)
		return self.manifest.append(record)

	def record_modified(
		self,
		doc: Any,
		original_values: dict[str, Any],
		*,
		capability: str | None = None,
	) -> ManifestRecord:
		"""Record a change to a pre-existing record so cleanup can restore it."""
		record = ManifestRecord(
			doctype=doc.doctype if hasattr(doc, "doctype") else str(doc),
			name=doc.name if hasattr(doc, "name") else str(doc),
			provider=self.current_provider,
			capability=capability or self.current_capability,
			operation="modified",
			original_values=dict(original_values),
		)
		return self.manifest.append(record)

	# -- reporting -----------------------------------------------------------
	def set_progress_callback(self, callback: ProgressCallback | None) -> None:
		self._progress_callback = callback

	def progress(self, message: str, *, current: int = 0, total: int = 0, **extra: Any) -> None:
		payload = {
			"provider": self.current_provider,
			"message": message,
			"current": current,
			"total": total,
			**extra,
		}
		if self._progress_callback:
			self._progress_callback(payload)

	def warning(self, message: str, **extra: Any) -> None:
		self._warnings.append({"provider": self.current_provider, "message": message, **extra})

	@property
	def warnings(self) -> list[dict[str, Any]]:
		return list(self._warnings)

	# -- document helpers ----------------------------------------------------
	def insert(
		self,
		payload: dict[str, Any],
		*,
		capability: str | None = None,
		submit: bool = False,
		dependencies: list[str] | None = None,
		logical_id: str | None = None,
	) -> Any:
		"""Insert (and optionally submit) a document through normal controllers.

		Direct SQL creation of business records is never used.
		"""
		return self.insert_doc(
			frappe.get_doc(payload),
			capability=capability,
			submit=submit,
			dependencies=dependencies,
			logical_id=logical_id,
		)

	def insert_doc(
		self,
		doc: Any,
		*,
		capability: str | None = None,
		submit: bool = False,
		dependencies: list[str] | None = None,
		logical_id: str | None = None,
	) -> Any:
		"""Insert an already-built document, such as one produced by an ERPNext mapper."""
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		self.record_created(doc, capability=capability, dependencies=dependencies, logical_id=logical_id)
		if submit:
			doc.submit()
			self.record_created(doc, capability=capability, dependencies=dependencies)
		return doc

	def submit(
		self, doc: Any, *, capability: str | None = None, dependencies: list[str] | None = None
	) -> Any:
		doc.submit()
		self.record_created(doc, capability=capability, dependencies=dependencies)
		return doc
