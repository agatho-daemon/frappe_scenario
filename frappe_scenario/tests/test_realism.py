# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Realism composition and insertion-free preview tests."""

from __future__ import annotations

import copy

import pytest

from frappe_scenario.archetypes import get_archetype
from frappe_scenario.core.random import DeterministicRandom
from frappe_scenario.core.realism_preview import representative_preview
from frappe_scenario.locales import get_country_pack
from frappe_scenario.providers.support.realism import RealismPipeline, name_findings, review_samples

pytestmark = pytest.mark.pure


def _choices(variation=0):
	return {
		"archetype": "hvac_distribution",
		"country": "Kuwait",
		"currency": "KWD",
		"preview_variation": variation,
	}


@pytest.mark.parametrize(
	"choices",
	[
		_choices(),
		{
			"archetype": "general_trading",
			"country": "United States",
			"currency": "USD",
			"preview_variation": 0,
		},
	],
)
def test_every_regional_preview_passes_deterministic_quality(choices):
	preview = representative_preview(choices)

	assert preview["quality"]["passed"]
	assert all(party["address"]["country"] == choices["country"] for party in preview["parties"])
	assert all(party["email"].endswith(".example") for party in preview["parties"])


def test_representative_preview_is_stable_until_variation_changes():
	first = representative_preview(_choices())
	second = representative_preview(_choices())
	varied = representative_preview(_choices(1))

	assert first == second
	assert varied["seed"] != first["seed"]
	assert varied["parties"] != first["parties"]


def test_preview_has_regional_parties_safe_contacts_and_reasonable_prices():
	preview = representative_preview(_choices())

	assert preview["quality"]["passed"]
	assert any(any("\u0600" <= char <= "\u06ff" for char in party["name"]) for party in preview["parties"])
	assert any(party["name"].isascii() for party in preview["parties"])
	assert all(not name_findings(party["name"]) for party in preview["parties"])
	assert all(party["email"].endswith(".example") for party in preview["parties"])
	assert all(party["address"]["country"] == "Kuwait" for party in preview["parties"])
	assert all(product["selling_price"] > product["cost"] > 0 for product in preview["products"])
	assert all("scenario testing" not in product["description"].lower() for product in preview["products"])
	assert preview["transaction_stories"]


def test_business_composition_uses_faker_primitives_not_faker_company():
	class PrimitiveFaker:
		def company(self):
			raise AssertionError("direct faker.company() must not be used")

		def first_name(self):
			return "Amina"

		def last_name(self):
			return "Al Sabah"

	pack = get_country_pack("Kuwait")
	pipeline = RealismPipeline(
		random=DeterministicRandom(19),
		primary_faker=PrimitiveFaker(),
		secondary_faker=PrimitiveFaker(),
		country_pack=pack,
		archetype=get_archetype("hvac_distribution"),
	)

	name = pipeline.business_name()

	assert "Al Sabah" in name or any(word in name for word in pack.business_words)
	assert any(form in name for form in pack.legal_forms)


def test_optional_ai_review_can_only_add_findings():
	samples = representative_preview(_choices())
	before = copy.deepcopy(samples)

	result = review_samples(
		samples,
		ai_reviewer=lambda payload: [
			{"field": "parties.0.name", "severity": "warning", "message": "Consider a shorter name."}
		],
	)

	assert result["ai_review"] == "completed"
	assert len(result["ai_findings"]) == 1
	assert samples == before
