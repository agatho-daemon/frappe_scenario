# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Deterministic realism composition and plausibility checks.

Faker supplies seeded primitives. Country packs and archetypes supply the
commercial vocabulary and shape. Generated values are accepted only after
syntactic, cultural-boundary, duplication, and visibly-synthetic checks.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

_SPACES = re.compile(r"\s+")
_REPEATED_WORD = re.compile(r"\b([\w\u0600-\u06ff]+)(?:\s+\1)\b", re.IGNORECASE)
_VISIBLE_SYNTHETIC = re.compile(r"(?:^|[\s_-])(?:_?test|fake|dummy|sample)(?:$|[\s_-])", re.IGNORECASE)
_BAD_PUNCTUATION = re.compile(r"[,/&-]{2,}")


@dataclass(frozen=True)
class PlausibilityFinding:
	field: str
	message: str
	severity: str = "warning"

	def as_dict(self) -> dict[str, str]:
		return {"field": self.field, "message": self.message, "severity": self.severity}


class RealismPipeline:
	"""Compose and filter party, contact, address, and catalog samples."""

	def __init__(
		self,
		*,
		random: Any,
		primary_faker: Any,
		secondary_faker: Any,
		country_pack: Any,
		archetype: Any,
		primary_share: float = 0.6,
	):
		self.random = random
		self.primary_faker = primary_faker
		self.secondary_faker = secondary_faker
		self.pack = country_pack
		self.archetype = archetype
		self.primary_share = float(primary_share)

	def business_name(self, locale_source: str | None = None) -> str:
		"""Build a regional commercial name from curated and Faker primitives."""
		for _ in range(30):
			if locale_source == "primary":
				faker = self.primary_faker
			elif locale_source == "secondary":
				faker = self.secondary_faker
			else:
				faker = self.primary_faker if self.random.chance(self.primary_share) else self.secondary_faker
			founder = _clean(faker.last_name())
			brand = self.random.choice(list(self.pack.business_words))
			sector = self.random.choice(self._sector_terms())
			legal_form = self.random.choice(list(self.pack.legal_forms))
			patterns = (
				("{founder} {sector} {legal_form}",)
				if locale_source
				else (
					"{brand} {sector} {legal_form}",
					"{founder} {sector} {legal_form}",
					"{brand} {legal_form}",
				)
			)
			pattern = self.random.choice(patterns)
			candidate = _clean(
				pattern.format(
					brand=brand,
					founder=founder,
					sector=sector,
					legal_form=legal_form,
				)
			)
			if not name_findings(candidate):
				return candidate
		return f"{self.random.choice(list(self.pack.business_words))} {self.pack.company_suffix}"

	def person_name(self, faker: Any | None = None) -> tuple[str, str]:
		source = faker or (
			self.primary_faker if self.random.chance(self.primary_share) else self.secondary_faker
		)
		for _ in range(20):
			first = _clean(source.first_name())
			last = _clean(source.last_name())
			if first and last and not name_findings(f"{first} {last}", allow_legal_form=False):
				return first, last
		return "Amina", "Hassan"

	def address(self, faker: Any | None = None) -> dict[str, Any]:
		address = self.pack.address(self.random, faker or self.primary_faker)
		findings = address_findings(address, expected_country=self.pack.country)
		if findings:
			raise ValueError("; ".join(finding.message for finding in findings))
		return address

	def _sector_terms(self) -> list[str]:
		terms = [self.archetype.industry]
		terms.extend(self.archetype.item_groups)
		terms.extend(family.title for family in self.archetype.families)
		cleaned = [_clean(term).replace("Equipment", "Systems") for term in terms if _clean(term)]
		return cleaned or ["Trading"]


def name_findings(value: str, *, allow_legal_form: bool = True) -> list[PlausibilityFinding]:
	value = _clean(value)
	findings = []
	if len(value) < 3 or len(value) > 100:
		findings.append(PlausibilityFinding("name", "Name length is outside the accepted range.", "error"))
	if _VISIBLE_SYNTHETIC.search(value):
		findings.append(PlausibilityFinding("name", "Name contains visibly synthetic boilerplate.", "error"))
	if _REPEATED_WORD.search(value):
		findings.append(PlausibilityFinding("name", "Name repeats the same word.", "error"))
	if _BAD_PUNCTUATION.search(value):
		findings.append(PlausibilityFinding("name", "Name contains an awkward punctuation sequence."))
	if not allow_legal_form and re.search(r"\b(?:LLC|Ltd|W\.L\.L|K\.S\.C\.C)\.?$", value, re.I):
		findings.append(
			PlausibilityFinding("name", "A personal name contains a company legal form.", "error")
		)
	return findings


def address_findings(
	address: dict[str, Any],
	*,
	expected_country: str,
) -> list[PlausibilityFinding]:
	findings = []
	for field in ("address_line1", "city", "country"):
		if not str(address.get(field) or "").strip():
			findings.append(PlausibilityFinding(field, f"Address is missing {field}.", "error"))
	if address.get("country") != expected_country:
		findings.append(
			PlausibilityFinding("country", "Address country conflicts with its regional pack.", "error")
		)
	return findings


def review_samples(
	samples: dict[str, Any],
	*,
	ai_reviewer: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
	"""Run deterministic quality checks and optionally collect AI suggestions.

	The optional reviewer can only return findings; it cannot mutate approved
	samples or create documents. Milestone 4 will supply provider adapters.
	"""
	findings: list[dict[str, Any]] = []
	for party in samples.get("parties") or []:
		findings.extend(finding.as_dict() for finding in name_findings(party["name"]))
		findings.extend(
			finding.as_dict()
			for finding in address_findings(
				party["address"],
				expected_country=samples["country"],
			)
		)
	for product in samples.get("products") or []:
		findings.extend(
			finding.as_dict() for finding in name_findings(product["name"], allow_legal_form=False)
		)
	ai_findings = ai_reviewer(samples) if ai_reviewer else []
	return {
		"passed": not any(finding.get("severity") == "error" for finding in [*findings, *ai_findings]),
		"deterministic_findings": findings,
		"ai_findings": ai_findings,
		"ai_review": "completed" if ai_reviewer else "not_requested",
	}


def _clean(value: Any) -> str:
	return _SPACES.sub(" ", str(value or "")).strip(" ,-/")
