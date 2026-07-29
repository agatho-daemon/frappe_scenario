# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Compatibility adapters for Frappe/ERPNext v15, v16, and develop.

Adapters translate *moved helpers, renamed fields, and optional DocTypes*. They
never bypass business validation: every document still goes through the normal
controller lifecycle.
"""

from __future__ import annotations

import functools
import importlib
from typing import Any

import frappe

from frappe_scenario.compatibility.base import CompatibilityAdapter
from frappe_scenario.compatibility.develop import DevelopAdapter
from frappe_scenario.compatibility.v15 import V15Adapter
from frappe_scenario.compatibility.v16 import V16Adapter

__all__ = [
	"CompatibilityAdapter",
	"app_major",
	"compatibility_level",
	"framework_major",
	"get_adapter",
	"installed_app_versions",
]


def _major(version: str | None) -> int:
	if not version:
		return 0
	try:
		return int(str(version).lstrip("v").split(".", 1)[0])
	except (TypeError, ValueError):
		return 0


def framework_major() -> int:
	"""Major version of the installed Frappe framework."""
	return _major(getattr(frappe, "__version__", None))


def app_major(app: str) -> int:
	"""Major version of an installed app, or ``0`` when it is not installed."""
	try:
		module = importlib.import_module(app)
	except ImportError:
		return 0
	return _major(getattr(module, "__version__", None))


def installed_app_versions() -> dict[str, str]:
	versions: dict[str, str] = {}
	for app in frappe.get_installed_apps():
		try:
			module = importlib.import_module(app)
		except ImportError:  # pragma: no cover - defensive
			continue
		versions[app] = str(getattr(module, "__version__", "unknown"))
	return dict(sorted(versions.items()))


@functools.lru_cache(maxsize=8)
def _adapter_for(major: int) -> CompatibilityAdapter:
	if major <= 15:
		return V15Adapter()
	if major == 16:
		return V16Adapter()
	return DevelopAdapter()


def get_adapter() -> CompatibilityAdapter:
	"""Return the adapter matching the installed framework."""
	return _adapter_for(framework_major())


def compatibility_level() -> dict[str, Any]:
	"""The fingerprint that scopes determinism guarantees."""
	import faker

	return {
		"adapter": get_adapter().id,
		"frappe_major": framework_major(),
		"erpnext_major": app_major("erpnext"),
		"faker": getattr(faker, "VERSION", "unknown"),
	}
