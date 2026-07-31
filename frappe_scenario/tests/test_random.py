# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Determinism of the seeded random service."""

import pytest

from frappe_scenario.archetypes import get_archetype
from frappe_scenario.core.random import DeterministicRandom, RandomService, derive_seed
from frappe_scenario.providers.support.naming import item_code

pytestmark = pytest.mark.pure


def test_item_codes_can_be_namespaced_for_coexisting_company_catalogs():
	family = get_archetype("hvac_distribution").families[0]
	assert item_code(family, 1) != item_code(family, 1, namespace="WCS")
	assert item_code(family, 1, namespace="WCS").startswith("WCS-")


def test_derive_seed_is_stable_and_order_sensitive():
	assert derive_seed(7, "erpnext.selling", "orders") == derive_seed(7, "erpnext.selling", "orders")
	assert derive_seed(7, "a", "b") != derive_seed(7, "b", "a")
	assert derive_seed(7, "a") != derive_seed(8, "a")


def test_two_streams_from_the_same_seed_agree():
	left = DeterministicRandom(derive_seed(11, "catalog"))
	right = DeterministicRandom(derive_seed(11, "catalog"))
	assert [left.randint(0, 1000) for _ in range(50)] == [right.randint(0, 1000) for _ in range(50)]


def test_streams_for_different_providers_diverge():
	service = RandomService(root_seed=11)
	buying = service.random("erpnext.buying")
	selling = service.random("erpnext.selling")
	assert [buying.random() for _ in range(20)] != [selling.random() for _ in range(20)]


def test_one_provider_stream_is_independent_of_call_order():
	"""A provider's stream must not shift when another provider draws first.

	This is what lets a scenario keep its shape when an unrelated provider is
	added, removed, or reordered.
	"""
	first = RandomService(root_seed=3)
	first.random("erpnext.buying").random()
	expected = [first.random("erpnext.selling").random() for _ in range(5)]

	second = RandomService(root_seed=3)
	assert [second.random("erpnext.selling").random() for _ in range(5)] == expected


def test_distribute_allocates_every_unit():
	random = DeterministicRandom(5)
	allocation = random.distribute(100, {"a": 3, "b": 1})
	assert sum(allocation.values()) == 100
	assert allocation["a"] > allocation["b"]


def test_distribute_handles_a_total_smaller_than_the_number_of_keys():
	random = DeterministicRandom(5)
	allocation = random.distribute(1, {"a": 1, "b": 1, "c": 1})
	assert sum(allocation.values()) == 1


def test_weighted_key_only_returns_keys_with_weight():
	random = DeterministicRandom(9)
	drawn = {random.weighted_key({"cash": 1, "net_30": 3, "never": 0}) for _ in range(200)}
	assert drawn <= {"cash", "net_30"}


def test_chance_respects_its_bounds():
	random = DeterministicRandom(2)
	assert all(random.chance(1.0) for _ in range(20))
	assert not any(random.chance(0.0) for _ in range(20))


def test_fingerprint_records_the_library_versions_that_scope_comparability():
	fingerprint = RandomService(root_seed=42, locales=["ar_AA"]).fingerprint()
	assert fingerprint["locales"] == ["ar_AA"]
	assert fingerprint["faker"]
