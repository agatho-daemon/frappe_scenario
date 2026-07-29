# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Provider discovery.

Providers are declared by installed apps in ``hooks.py``::

    scenario_providers = [
        "my_app.scenarios.provider.MyProvider",
    ]

Only paths declared this way are ever resolved. A path supplied by an API
caller, an AI model, or a specification is never imported: the registry is the
single source of truth and lookups are by provider id.
"""

from __future__ import annotations

import importlib
import re
from typing import Any

import frappe

from frappe_scenario.core.errors import DiscoveryError
from frappe_scenario.core.provider import ScenarioProvider

HOOK_NAME = "scenario_providers"

_PATH_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$")
_CAPABILITY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


class ProviderRegistry:
	"""An immutable snapshot of the providers available on this site."""

	def __init__(self, providers: dict[str, ScenarioProvider], capabilities: dict[str, str]):
		self._providers = providers
		self._capabilities = capabilities

	def __contains__(self, provider_id: object) -> bool:
		return provider_id in self._providers

	def __len__(self) -> int:
		return len(self._providers)

	@property
	def providers(self) -> list[ScenarioProvider]:
		return [self._providers[key] for key in sorted(self._providers)]

	@property
	def capability_owners(self) -> dict[str, str]:
		return dict(self._capabilities)

	def get(self, provider_id: str) -> ScenarioProvider:
		"""Look a provider up by id. Never imports an arbitrary path."""
		provider = self._providers.get(provider_id)
		if not provider:
			raise DiscoveryError(
				f"Unknown scenario provider {provider_id!r}.",
				provider=provider_id,
				phase="discovery",
				details={"available": sorted(self._providers)},
			)
		return provider

	def owner_of(self, capability: str) -> str | None:
		return self._capabilities.get(capability)

	def declared_capabilities(self) -> dict[str, dict[str, Any]]:
		declarations: dict[str, dict[str, Any]] = {}
		for provider in self.providers:
			for capability in provider.capabilities:
				payload = capability.as_dict()
				payload["provider"] = provider.id
				payload["provider_version"] = provider.version
				declarations[capability.id] = payload
			for capability_id in provider.provides_capabilities:
				declarations.setdefault(
					capability_id,
					{
						"id": capability_id,
						"description": "",
						"provider": provider.id,
						"provider_version": provider.version,
						"doctypes": [],
						"requires": [],
						"optional_requires": [],
						"estimated_records": "unknown",
						"safety": "",
						"validation_rules": [],
						"incompatible_with": [],
						"example": None,
					},
				)
		return dict(sorted(declarations.items()))

	def versions(self) -> dict[str, str]:
		return {provider.id: provider.version for provider in self.providers}


def _hook_paths() -> list[tuple[str, str]]:
	"""Return ``(app, dotted_path)`` pairs from installed apps' hooks."""
	pairs: list[tuple[str, str]] = []
	for app in frappe.get_installed_apps():
		app_hooks = frappe.get_hooks(app_name=app).get(HOOK_NAME) or []
		for path in app_hooks:
			pairs.append((app, path))
	return pairs


def _resolve(app: str, path: str) -> type[ScenarioProvider]:
	if not _PATH_PATTERN.match(path):
		raise DiscoveryError(
			f"Provider path {path!r} declared by {app!r} is not a valid dotted path.",
			phase="discovery",
			details={"app": app, "path": path},
		)

	module_path, _, attribute = path.rpartition(".")
	root = module_path.split(".", 1)[0]
	if root not in frappe.get_installed_apps():
		raise DiscoveryError(
			f"Provider path {path!r} does not belong to an installed app.",
			phase="discovery",
			details={"app": app, "path": path, "root_module": root},
		)

	try:
		module = importlib.import_module(module_path)
	except ImportError as exception:
		raise DiscoveryError(
			f"Could not import provider module {module_path!r}: {exception}",
			phase="discovery",
			details={"app": app, "path": path},
		) from exception

	provider_class = getattr(module, attribute, None)
	if provider_class is None:
		raise DiscoveryError(
			f"Provider module {module_path!r} has no attribute {attribute!r}.",
			phase="discovery",
			details={"app": app, "path": path},
		)

	if not (isinstance(provider_class, type) and issubclass(provider_class, ScenarioProvider)):
		raise DiscoveryError(
			f"{path!r} is not a ScenarioProvider subclass.",
			phase="discovery",
			details={"app": app, "path": path},
		)

	return provider_class


def _validate_metadata(provider: ScenarioProvider, app: str, path: str) -> None:
	if not provider.id:
		raise DiscoveryError(f"Provider {path!r} does not declare an id.", phase="discovery")
	if not _CAPABILITY_PATTERN.match(provider.id):
		raise DiscoveryError(
			f"Provider id {provider.id!r} must be a lowercase namespaced identifier "
			"such as 'erpnext.trading'.",
			provider=provider.id,
			phase="discovery",
		)
	for capability_id in provider.provides_capabilities:
		if not _CAPABILITY_PATTERN.match(capability_id):
			raise DiscoveryError(
				f"Capability id {capability_id!r} declared by {provider.id!r} is not namespaced.",
				provider=provider.id,
				capability=capability_id,
				phase="discovery",
			)
	declared = {capability.id for capability in provider.capabilities}
	undeclared = declared - set(provider.provides_capabilities)
	if undeclared:
		raise DiscoveryError(
			f"Provider {provider.id!r} documents capabilities it does not declare in "
			f"provides_capabilities: {sorted(undeclared)}.",
			provider=provider.id,
			phase="discovery",
		)
	if not provider.app:
		provider.app = app


def _app_available(provider: ScenarioProvider) -> tuple[bool, str | None]:
	installed = set(frappe.get_installed_apps())
	for app_name in provider.requires_apps:
		if app_name not in installed:
			return False, f"requires app {app_name!r} which is not installed"

	if provider.supported_frappe_versions:
		from frappe_scenario.compatibility import framework_major

		if framework_major() not in provider.supported_frappe_versions:
			return False, (
				f"requires Frappe major version in {sorted(provider.supported_frappe_versions)}, "
				f"found {framework_major()}"
			)
	return True, None


def discover_providers(*, include_unavailable: bool = False) -> ProviderRegistry:
	"""Build the provider registry for the current site.

	Duplicate provider ids and duplicate capability owners are rejected: a
	scenario must have exactly one authority for each capability.
	"""
	providers: dict[str, ScenarioProvider] = {}
	sources: dict[str, str] = {}
	capabilities: dict[str, str] = {}

	for app, path in _hook_paths():
		provider = _resolve(app, path)()
		_validate_metadata(provider, app, path)

		if provider.id in providers:
			raise DiscoveryError(
				f"Duplicate scenario provider id {provider.id!r} declared by {sources[provider.id]!r} "
				f"and {path!r}.",
				provider=provider.id,
				phase="discovery",
			)

		available, _reason = _app_available(provider)
		if not available and not include_unavailable:
			continue

		providers[provider.id] = provider
		sources[provider.id] = path

		for capability_id in provider.provides_capabilities:
			if capability_id in capabilities:
				raise DiscoveryError(
					f"Capability {capability_id!r} is claimed by both {capabilities[capability_id]!r} "
					f"and {provider.id!r}.",
					provider=provider.id,
					capability=capability_id,
					phase="discovery",
				)
			capabilities[capability_id] = provider.id

	return ProviderRegistry(providers, capabilities)


def unavailable_providers() -> list[dict[str, Any]]:
	"""Providers declared by installed apps that cannot run on this site."""
	results: list[dict[str, Any]] = []
	for app, path in _hook_paths():
		try:
			provider = _resolve(app, path)()
		except DiscoveryError as exception:
			results.append({"path": path, "app": app, "reason": exception.message})
			continue
		available, reason = _app_available(provider)
		if not available:
			results.append({"id": provider.id, "app": app, "path": path, "reason": reason})
	return results
