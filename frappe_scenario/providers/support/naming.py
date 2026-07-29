# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Naming.

Generated names must be recognisably synthetic yet plausible enough to be
readable in a demo. Codes are stable for a given seed, which is what allows the
canonical logical hash to compare two runs.
"""

from __future__ import annotations

import re
from typing import Any

from frappe_scenario.archetypes.base import ItemFamily

_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")

MODEL_LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"


def slugify(value: str, *, separator: str = "-") -> str:
	cleaned = _NON_ALNUM.sub(separator, str(value)).strip(separator)
	return cleaned.lower() or "item"


def family_prefix(family: ItemFamily) -> str:
	"""Short uppercase code derived from the family key, for example ``SAC``."""
	words = [word for word in family.key.split("_") if word not in {"and", "of"}]
	if len(words) >= 3:
		return "".join(word[0] for word in words[:3]).upper()
	if len(words) == 2:
		return (words[0][:2] + words[1][:1]).upper()
	return words[0][:3].upper()


def item_code(family: ItemFamily, index: int) -> str:
	return f"{family_prefix(family)}-{index:04d}"


def item_name(random: Any, family: ItemFamily) -> str:
	"""A readable product name built from the family's descriptor vocabulary."""
	descriptor = random.choice(list(family.descriptors)) if family.descriptors else family.title
	model = (
		f"{random.choice(list(MODEL_LETTERS))}{random.choice(list(MODEL_LETTERS))}{random.randint(10, 99)}"
	)
	singular = family.title.rstrip("s") if family.title.endswith("s") else family.title
	return f"{descriptor} {singular} {model}"


def party_name(random: Any, faker_primary: Any, faker_secondary: Any, *, primary_share: float = 0.6) -> str:
	"""Company-style party name, mixing the primary and secondary locales."""
	source = faker_primary if random.chance(primary_share) else faker_secondary
	return str(source.company()).strip()


def unique_name(base: str, taken: set[str]) -> str:
	"""Append a numeric discriminator until the name is unused."""
	candidate = base
	suffix = 2
	while candidate in taken:
		candidate = f"{base} {suffix}"
		suffix += 1
	taken.add(candidate)
	return candidate


def person_name(faker: Any) -> tuple[str, str]:
	return str(faker.first_name()).strip(), str(faker.last_name()).strip()
