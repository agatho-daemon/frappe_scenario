# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Country pack registry.

Built-in packs ship with this app. Installed apps may contribute more through
the ``scenario_country_packs`` hook::

    scenario_country_packs = ["my_app.scenario.locales.oman.COUNTRY_PACK"]

An unknown country resolves to the generic international pack with the requested
country name preserved, so a scenario never fails purely because nobody has
written a pack yet.
"""

from __future__ import annotations

import importlib
import re
from copy import deepcopy
from typing import Any

from frappe_scenario.core.errors import DiscoveryError
from frappe_scenario.locales.base import CountryPack

__all__ = [
	"CountryPack",
	"describe_country_packs",
	"get_country_pack",
	"list_country_packs",
]

HOOK_NAME = "scenario_country_packs"

_BUILTIN = (
	"frappe_scenario.locales.kuwait.COUNTRY_PACK",
	"frappe_scenario.locales.generic_international.COUNTRY_PACK",
)

_FALLBACK = "generic_international"

_DOTTED_PATH = re.compile(r"^[a-zA-Z_][\w.]*$")


def _load(path: str) -> CountryPack:
	if not _DOTTED_PATH.match(path):
		raise DiscoveryError(f"Invalid country pack path {path!r}.", phase="discovery")
	module_path, _, attribute = path.rpartition(".")
	try:
		module = importlib.import_module(module_path)
	except ImportError as exception:
		raise DiscoveryError(
			f"Cannot import country pack module {module_path!r}: {exception}", phase="discovery"
		) from exception
	pack = getattr(module, attribute, None)
	if not isinstance(pack, CountryPack):
		raise DiscoveryError(f"{path!r} is not a CountryPack instance.", phase="discovery")
	return pack


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
		# Country packs must remain usable without a site, for pure unit tests.
		return []


def _registry() -> dict[str, CountryPack]:
	registry: dict[str, CountryPack] = {}
	for path in [*_BUILTIN, *_hook_paths()]:
		pack = _load(path)
		existing = registry.get(pack.id)
		if existing is not None and existing is not pack:
			raise DiscoveryError(
				f"Country pack id {pack.id!r} is declared more than once.",
				phase="discovery",
				details={"path": path},
			)
		registry[pack.id] = pack
	return registry


def _by_country() -> dict[str, CountryPack]:
	return {pack.country.strip().lower(): pack for pack in _registry().values()}


def get_country_pack(country: str | None) -> CountryPack:
	"""Resolve a country name to its pack, falling back to the generic pack."""
	registry = _registry()
	key = (country or "").strip()
	if not key:
		return registry[_FALLBACK]

	if key in registry:
		return registry[key]

	match = _by_country().get(key.lower())
	if match is not None:
		return match

	# Unknown country: keep generic conventions but preserve the country name so
	# Address and Company records still say what the scenario asked for.
	fallback = deepcopy(registry[_FALLBACK])
	fallback.country = key
	return fallback


def list_country_packs() -> list[str]:
	return sorted(_registry())


def describe_country_packs() -> list[dict[str, Any]]:
	return [pack.describe() for _, pack in sorted(_registry().items())]
