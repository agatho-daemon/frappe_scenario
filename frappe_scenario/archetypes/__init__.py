# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Archetype registry.

Built-in archetypes ship with this app. Any installed app may contribute more
through the ``scenario_archetypes`` hook, exactly as it contributes providers::

    scenario_archetypes = ["my_app.scenario.archetypes.pharmacy.ARCHETYPE"]
"""

from __future__ import annotations

import importlib
import re
from typing import Any

from frappe_scenario.archetypes.base import KIND_MARGIN_RANK, Archetype, ItemFamily
from frappe_scenario.core.errors import DiscoveryError, SpecificationError

__all__ = [
	"KIND_MARGIN_RANK",
	"Archetype",
	"ItemFamily",
	"describe_archetypes",
	"get_archetype",
	"list_archetypes",
]

HOOK_NAME = "scenario_archetypes"

_BUILTIN = (
	"frappe_scenario.archetypes.hvac_distribution.ARCHETYPE",
	"frappe_scenario.archetypes.general_trading.ARCHETYPE",
)

_DOTTED_PATH = re.compile(r"^[a-zA-Z_][\w.]*$")


def _load(path: str) -> Archetype:
	if not _DOTTED_PATH.match(path):
		raise DiscoveryError(f"Invalid archetype path {path!r}.", phase="discovery")
	module_path, _, attribute = path.rpartition(".")
	try:
		module = importlib.import_module(module_path)
	except ImportError as exception:
		raise DiscoveryError(
			f"Cannot import archetype module {module_path!r}: {exception}", phase="discovery"
		) from exception
	archetype = getattr(module, attribute, None)
	if not isinstance(archetype, Archetype):
		raise DiscoveryError(f"{path!r} is not an Archetype instance.", phase="discovery")
	return archetype


def _hook_paths() -> list[str]:
	try:
		import frappe

		if not getattr(frappe.local, "site", None):
			return []
		paths: list[str] = []
		for app_name in frappe.get_installed_apps():
			paths.extend(frappe.get_hooks(HOOK_NAME, app_name=app_name) or [])
		return paths
	except Exception:
		# Archetypes must remain usable in a pure-Python unit test with no site.
		return []


def _registry() -> dict[str, Archetype]:
	registry: dict[str, Archetype] = {}
	for path in [*_BUILTIN, *_hook_paths()]:
		archetype = _load(path)
		existing = registry.get(archetype.id)
		if existing is not None and existing is not archetype:
			raise DiscoveryError(
				f"Archetype id {archetype.id!r} is declared more than once.",
				phase="discovery",
				details={"path": path},
			)
		registry[archetype.id] = archetype
	return registry


def get_archetype(archetype_id: str) -> Archetype:
	registry = _registry()
	if archetype_id not in registry:
		raise SpecificationError(
			f"Unknown archetype {archetype_id!r}.",
			phase="resolve",
			details={"available": sorted(registry)},
		)
	return registry[archetype_id]


def list_archetypes() -> list[str]:
	return sorted(_registry())


def describe_archetypes() -> list[dict[str, Any]]:
	return [archetype.describe() for _, archetype in sorted(_registry().items())]
