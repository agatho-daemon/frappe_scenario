# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Capability catalogue endpoints.

The catalogue is the contract between an external agent and this platform: it
describes what can be generated, never how to generate it.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import frappe

from frappe_scenario.archetypes import describe_archetypes
from frappe_scenario.compatibility import compatibility_level, installed_app_versions
from frappe_scenario.core.discovery import discover_providers, unavailable_providers
from frappe_scenario.core.scale import describe_scale_profiles
from frappe_scenario.core.specification import SCHEMA_VERSION, get_schema
from frappe_scenario.locales import describe_country_packs

ROLE = "System Manager"


@frappe.whitelist()
def describe_capabilities() -> dict[str, Any]:
	"""Everything an agent needs to compile a specification, plus its hash."""
	frappe.only_for(ROLE)
	return capability_catalog()


def capability_catalog() -> dict[str, Any]:
	registry = discover_providers()
	catalog = {
		"schema_version": SCHEMA_VERSION,
		"schema": get_schema(),
		"providers": [provider.describe() for provider in registry.providers],
		"capabilities": registry.declared_capabilities(),
		"unavailable_providers": unavailable_providers(),
		"archetypes": describe_archetypes(),
		"country_packs": describe_country_packs(),
		"scales": describe_scale_profiles(),
		"compatibility": compatibility_level(),
		"installed_apps": installed_app_versions(),
	}
	catalog["catalog_hash"] = catalog_hash(catalog)
	return catalog


def catalog_hash(catalog: dict[str, Any]) -> str:
	"""Identifies the catalogue a draft was compiled against.

	Site-specific values are excluded so the same app versions produce the same
	hash on every site.
	"""
	payload = {
		"schema_version": catalog["schema_version"],
		"capabilities": catalog["capabilities"],
		"archetypes": catalog["archetypes"],
		"country_packs": catalog["country_packs"],
		"scales": catalog["scales"],
	}
	encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
	return hashlib.sha256(encoded).hexdigest()
