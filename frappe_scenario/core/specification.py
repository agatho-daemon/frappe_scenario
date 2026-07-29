# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Scenario specification loading, validation, and resolution.

The specification is the authoritative input. Everything downstream - planning,
generation, validation, cleanup, and the canonical logical hash - reads the
*resolved* specification produced here, never the raw user input.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
from copy import deepcopy
from typing import Any

from frappe_scenario.core.errors import SpecificationError
from frappe_scenario.core.scale import DEFAULT_SCALE, get_scale_profile

SCHEMA_VERSION = "1.0"
_SCHEMA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema")

# Anything larger is refused before execution; it is almost always a mistake.
MAX_SPECIFICATION_BYTES = 512 * 1024


def get_schema() -> dict[str, Any]:
	"""Return the public, versioned JSON Schema for the specification."""
	path = os.path.join(_SCHEMA_DIR, f"scenario-{SCHEMA_VERSION}.json")
	with open(path, encoding="utf-8") as handle:
		return json.load(handle)


def load_specification(source: str | bytes | dict[str, Any]) -> dict[str, Any]:
	"""Parse YAML or JSON text (or accept an already-parsed mapping).

	The parser is deliberately restricted: YAML is read with ``safe_load`` so no
	Python object construction is possible from untrusted content.
	"""
	if isinstance(source, dict):
		return deepcopy(source)

	if isinstance(source, bytes):
		source = source.decode("utf-8")

	if not isinstance(source, str):
		raise SpecificationError("Specification must be a mapping, JSON text, or YAML text.", phase="load")

	if len(source.encode("utf-8")) > MAX_SPECIFICATION_BYTES:
		raise SpecificationError(
			f"Specification exceeds the {MAX_SPECIFICATION_BYTES} byte limit.", phase="load"
		)

	text = source.strip()
	if not text:
		raise SpecificationError("Specification is empty.", phase="load")

	if text.startswith("{"):
		try:
			parsed = json.loads(text)
		except ValueError as exception:
			raise SpecificationError(f"Invalid JSON: {exception}", phase="load") from exception
	else:
		import yaml

		try:
			parsed = yaml.safe_load(text)
		except yaml.YAMLError as exception:
			raise SpecificationError(f"Invalid YAML: {exception}", phase="load") from exception

	if not isinstance(parsed, dict):
		raise SpecificationError("Specification must decode to a mapping.", phase="load")
	return parsed


def read_specification_file(path: str) -> dict[str, Any]:
	if not os.path.isfile(path):
		raise SpecificationError(f"Specification file not found: {path}", phase="load")
	with open(path, encoding="utf-8") as handle:
		return load_specification(handle.read())


def validate_schema(spec: dict[str, Any]) -> list[dict[str, Any]]:
	"""Validate against the JSON Schema. Returns a list of structured problems."""
	import jsonschema

	validator_class = jsonschema.validators.validator_for(get_schema())
	validator = validator_class(get_schema())
	problems: list[dict[str, Any]] = []
	for error in sorted(validator.iter_errors(spec), key=lambda item: list(item.absolute_path)):
		pointer = "/" + "/".join(str(part) for part in error.absolute_path)
		problems.append(
			{
				"severity": "error",
				"rule": "specification.schema",
				"path": pointer,
				"message": error.message,
			}
		)
	return problems


def _validate_semantics(spec: dict[str, Any]) -> list[dict[str, Any]]:
	"""Checks the schema cannot express: ranges, date sanity, distributions."""
	problems: list[dict[str, Any]] = []

	catalog = spec.get("catalog") or {}
	margin_range = catalog.get("gross_margin_range")
	if margin_range and margin_range[0] > margin_range[1]:
		problems.append(
			{
				"severity": "error",
				"rule": "specification.margin_range",
				"path": "/catalog/gross_margin_range",
				"message": "gross_margin_range lower bound is greater than the upper bound.",
			}
		)
	for family, override in (catalog.get("family_margin_overrides") or {}).items():
		if override[0] > override[1]:
			problems.append(
				{
					"severity": "error",
					"rule": "specification.margin_range",
					"path": f"/catalog/family_margin_overrides/{family}",
					"message": "Margin override lower bound is greater than the upper bound.",
				}
			)

	anchor = (spec.get("scenario") or {}).get("anchor_date")
	if anchor:
		try:
			datetime.date.fromisoformat(anchor)
		except ValueError:
			problems.append(
				{
					"severity": "error",
					"rule": "specification.anchor_date",
					"path": "/scenario/anchor_date",
					"message": f"anchor_date {anchor!r} is not a valid calendar date.",
				}
			)

	for section, key in (("parties", "customer_segments"), ("parties", "payment_terms")):
		distribution = (spec.get(section) or {}).get(key)
		if distribution and sum(float(value) for value in distribution.values()) <= 0:
			problems.append(
				{
					"severity": "error",
					"rule": "specification.distribution",
					"path": f"/{section}/{key}",
					"message": "Distribution weights must include at least one positive value.",
				}
			)

	scale = (spec.get("scenario") or {}).get("scale")
	if scale == "custom":
		parties = spec.get("parties") or {}
		if not parties.get("customers") or not parties.get("suppliers"):
			problems.append(
				{
					"severity": "error",
					"rule": "specification.custom_scale",
					"path": "/parties",
					"message": "scale 'custom' requires explicit parties.customers and parties.suppliers.",
				}
			)

	return problems


def _deep_default(target: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
	"""Fill missing keys from ``defaults`` without overwriting explicit values."""
	for key, value in defaults.items():
		if isinstance(value, dict):
			target[key] = _deep_default(dict(target.get(key) or {}), value)
		elif key not in target or target[key] is None:
			target[key] = deepcopy(value)
	return target


def resolve_specification(spec: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
	"""Validate then apply archetype, scale, and country defaults.

	Returns ``(resolved_specification, assumptions)``. Assumptions record every
	value the platform inferred, so an agent or reviewer can see exactly what was
	not stated explicitly.
	"""
	problems = validate_schema(spec)
	if problems:
		raise SpecificationError(
			"Specification failed schema validation.",
			phase="validate_spec",
			details={"problems": problems},
		)

	semantic = _validate_semantics(spec)
	if semantic:
		raise SpecificationError(
			"Specification failed semantic validation.",
			phase="validate_spec",
			details={"problems": semantic},
		)

	from frappe_scenario.archetypes import get_archetype
	from frappe_scenario.locales import get_country_pack

	resolved = deepcopy(spec)
	assumptions: list[dict[str, Any]] = []

	def assume(path: str, value: Any, reason: str) -> None:
		assumptions.append({"path": path, "value": value, "reason": reason})

	scenario = resolved.setdefault("scenario", {})

	archetype = get_archetype(scenario["archetype"])
	scale_name = scenario.get("scale") or DEFAULT_SCALE
	if not scenario.get("scale"):
		scenario["scale"] = scale_name
		assume("/scenario/scale", scale_name, "No scale supplied; defaulted to the smoke profile.")

	country = scenario.get("country") or archetype.default_country
	if not scenario.get("country"):
		scenario["country"] = country
		assume("/scenario/country", country, f"Archetype {archetype.id} default country.")
	country_pack = get_country_pack(country)

	if not scenario.get("currency"):
		scenario["currency"] = country_pack.currency
		assume("/scenario/currency", country_pack.currency, f"Country pack {country_pack.id} currency.")

	locale = scenario.setdefault("locale", {})
	if not locale.get("primary"):
		locale["primary"] = country_pack.primary_locale
		assume("/scenario/locale/primary", locale["primary"], f"Country pack {country_pack.id} locale.")
	if not locale.get("secondary"):
		locale["secondary"] = country_pack.secondary_locale
		assume("/scenario/locale/secondary", locale["secondary"], "Country pack secondary locale.")

	if not scenario.get("anchor_date"):
		scenario["anchor_date"] = datetime.date.today().isoformat()
		assume("/scenario/anchor_date", scenario["anchor_date"], "No anchor date supplied; used today.")

	if scenario.get("seed") is None:
		digest = hashlib.blake2b(
			json.dumps(spec, sort_keys=True, default=str).encode("utf-8"), digest_size=4
		).digest()
		scenario["seed"] = int.from_bytes(digest, "big")
		assume("/scenario/seed", scenario["seed"], "No seed supplied; derived from the specification.")

	scale_profile = get_scale_profile(scale_name)
	if not scenario.get("history_months"):
		scenario["history_months"] = scale_profile["history_months"]
		assume("/scenario/history_months", scenario["history_months"], f"Scale profile {scale_name}.")

	# Layered defaults: scale profile first, then archetype, then country pack.
	before = deepcopy(resolved)
	for defaults, reason in (
		({k: v for k, v in scale_profile.items() if k != "description"}, f"scale profile {scale_name}"),
		(archetype.defaults(scale_name), f"archetype {archetype.id}"),
		(country_pack.specification_defaults(), f"country pack {country_pack.id}"),
	):
		_deep_default(resolved, {k: v for k, v in defaults.items() if k != "history_months"})
		for path, value in _diff_paths(before, resolved):
			assume(path, value, f"Inferred from {reason}.")
		before = deepcopy(resolved)

	resolved.setdefault("providers", {})
	resolved.setdefault("validation", {})
	resolved["schema_version"] = SCHEMA_VERSION

	# Re-validate: defaults must never produce an invalid specification.
	final_problems = validate_schema(resolved)
	if final_problems:
		raise SpecificationError(
			"Resolved specification failed schema validation.",
			phase="validate_spec",
			details={"problems": final_problems},
		)

	return resolved, assumptions


def _diff_paths(before: dict[str, Any], after: dict[str, Any], prefix: str = "") -> list[tuple[str, Any]]:
	"""Report JSON-pointer paths added by a defaulting pass."""
	changes: list[tuple[str, Any]] = []
	for key in sorted(after):
		path = f"{prefix}/{key}"
		new_value = after[key]
		old_value = before.get(key)
		if isinstance(new_value, dict) and isinstance(old_value, dict):
			changes.extend(_diff_paths(old_value, new_value, path))
		elif key not in before:
			changes.append((path, new_value))
	return changes


def specification_hash(spec: dict[str, Any]) -> str:
	"""Stable hash of a resolved specification, used for provenance and immutability."""
	payload = json.dumps(spec, sort_keys=True, separators=(",", ":"), default=str)
	return hashlib.sha256(payload.encode("utf-8")).hexdigest()
