# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Safe discovery for AI adapters declared by installed applications."""

from __future__ import annotations

import importlib
import re
from typing import Any

import frappe

from frappe_scenario.ai.base import AIAdapter

HOOK_NAME = "scenario_ai_adapters"
_PATH_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$")
_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


class AIAdapterRegistry:
	def __init__(self, adapters: dict[str, AIAdapter]):
		self._adapters = dict(adapters)

	@property
	def adapters(self) -> list[AIAdapter]:
		return [self._adapters[key] for key in sorted(self._adapters)]

	def get(self, adapter_id: str) -> AIAdapter:
		try:
			return self._adapters[adapter_id]
		except KeyError as exception:
			raise ValueError(
				f"Unknown AI adapter {adapter_id!r}; available: {sorted(self._adapters)}"
			) from exception


def discover_ai_adapters() -> AIAdapterRegistry:
	adapters: dict[str, AIAdapter] = {}
	installed = set(frappe.get_installed_apps())
	for app in sorted(installed):
		for path in frappe.get_hooks(app_name=app).get(HOOK_NAME) or []:
			adapter = _resolve(path, installed)
			if not _ID_PATTERN.fullmatch(adapter.id):
				raise ValueError(f"Invalid AI adapter id {adapter.id!r} declared by {path!r}.")
			if adapter.id in adapters:
				raise ValueError(f"Duplicate AI adapter id {adapter.id!r}.")
			adapters[adapter.id] = adapter
	return AIAdapterRegistry(adapters)


def _resolve(path: str, installed: set[str]) -> AIAdapter:
	if not _PATH_PATTERN.fullmatch(path):
		raise ValueError(f"Invalid AI adapter path {path!r}.")
	module_path, _, attribute = path.rpartition(".")
	if module_path.split(".", 1)[0] not in installed:
		raise ValueError(f"AI adapter {path!r} does not belong to an installed app.")
	adapter_class: Any = getattr(importlib.import_module(module_path), attribute, None)
	if not (isinstance(adapter_class, type) and issubclass(adapter_class, AIAdapter)):
		raise ValueError(f"{path!r} is not an AIAdapter subclass.")
	return adapter_class()
