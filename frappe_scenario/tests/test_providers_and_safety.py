# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Provider discovery, dependency resolution, safety, and compatibility.

These need a connected site because providers are registered through app hooks
and the compatibility layer reads installed app versions. They write nothing.
"""

import pytest

from frappe_scenario.core.dependency_graph import resolve_graph
from frappe_scenario.core.discovery import ProviderRegistry, discover_providers
from frappe_scenario.core.errors import DependencyError, SafetyError
from frappe_scenario.core.provider import ScenarioProvider

pytestmark = pytest.mark.frappe_site


@pytest.fixture(scope="module")
def registry(frappe_site):
	return discover_providers()


def test_every_registered_provider_declares_its_identity(registry):
	for provider in registry.providers:
		assert provider.id
		assert provider.version
		assert provider.description


def test_each_capability_has_exactly_one_owner(registry):
	for capability, owner in registry.capability_owners.items():
		assert registry.get(owner)
		assert capability in registry.get(owner).provides_capabilities


def test_a_declared_capability_is_backed_by_a_declaration(registry):
	"""``provides_capabilities`` and the ``capabilities`` list must agree.

	The first drives dependency resolution and the second is what an operator or
	an agent reads, so a capability present in one and absent from the other
	would be invisible to somebody choosing what to generate.
	"""
	for provider in registry.providers:
		declared = {declaration.id for declaration in provider.capabilities}
		assert declared == set(provider.provides_capabilities), provider.id


def test_the_execution_order_satisfies_every_requirement(registry):
	graph = resolve_graph(registry)
	published: set[str] = set()
	for provider in graph.order:
		missing = set(provider.requires_capabilities) - published
		assert not missing, f"{provider.id} runs before {missing}"
		published |= set(provider.provides_capabilities)


def test_resolution_is_stable(registry):
	first = [provider.id for provider in resolve_graph(registry).order]
	second = [provider.id for provider in resolve_graph(registry).order]
	assert first == second


def test_requesting_a_subset_pulls_in_what_it_depends_on(registry):
	graph = resolve_graph(registry, {"erpnext.selling"})
	ordered = [provider.id for provider in graph.order]
	assert "erpnext.selling" in ordered
	assert "erpnext.foundation" in ordered
	assert ordered.index("erpnext.foundation") < ordered.index("erpnext.selling")


def test_an_unsatisfiable_requirement_is_refused(registry):
	class Orphan(ScenarioProvider):
		id = "test.orphan"
		version = "1.0.0"
		description = "Requires something nobody publishes."
		requires_capabilities = {"nobody.publishes.this"}

	orphan = Orphan()
	extended = ProviderRegistry(
		{provider.id: provider for provider in [*registry.providers, orphan]},
		registry.capability_owners,
	)

	with pytest.raises(DependencyError):
		resolve_graph(extended, {"test.orphan"})


def test_a_dependency_cycle_is_refused():
	class Left(ScenarioProvider):
		id = "test.left"
		version = "1.0.0"
		description = "Waits on the right."
		provides_capabilities = {"test.left.thing"}
		requires_capabilities = {"test.right.thing"}

	class Right(ScenarioProvider):
		id = "test.right"
		version = "1.0.0"
		description = "Waits on the left."
		provides_capabilities = {"test.right.thing"}
		requires_capabilities = {"test.left.thing"}

	registry = ProviderRegistry(
		{"test.left": Left(), "test.right": Right()},
		{"test.left.thing": "test.left", "test.right.thing": "test.right"},
	)

	with pytest.raises(DependencyError):
		resolve_graph(registry)


def test_the_compatibility_level_identifies_what_a_hash_can_be_compared_against(frappe_site):
	from frappe_scenario.compatibility import compatibility_level, get_adapter

	level = compatibility_level()
	assert level["adapter"]
	assert level["frappe_major"] >= 15
	assert level["faker"]
	assert get_adapter().id == level["adapter"]


def test_the_adapter_reports_doctypes_and_fields_truthfully(frappe_site):
	from frappe_scenario.compatibility import get_adapter

	adapter = get_adapter()
	assert adapter.has_doctype("User")
	assert not adapter.has_doctype("No Such Doctype 12345")
	assert adapter.has_field("User", "email")
	assert not adapter.has_field("User", "no_such_field_12345")


def test_generation_is_refused_on_a_site_that_is_not_marked_disposable(frappe_site, monkeypatch):
	import frappe

	from frappe_scenario.core.safety import assert_safe_to_generate, site_safety_report

	monkeypatch.setitem(frappe.conf, "frappe_scenario_disposable", 0)
	monkeypatch.setitem(frappe.conf, "frappe_scenario_allow_non_disposable", 0)

	assert not site_safety_report()["disposable"]
	with pytest.raises(SafetyError):
		assert_safe_to_generate()


def test_the_test_site_itself_is_disposable(frappe_site):
	from frappe_scenario.core.safety import assert_safe_to_generate

	# Guards every other site test: they must never run against a real site.
	assert_safe_to_generate()


def test_the_capability_catalog_is_self_describing(frappe_site):
	from frappe_scenario.api.capabilities import capability_catalog

	catalog = capability_catalog()
	assert catalog["schema"]
	assert catalog["providers"]
	assert catalog["archetypes"]
	assert catalog["scales"]
	assert catalog["catalog_hash"]


def test_the_catalog_hash_covers_the_contract_and_ignores_the_site(frappe_site):
	from frappe_scenario.api.capabilities import capability_catalog, catalog_hash

	catalog = capability_catalog()
	assert catalog_hash(catalog) == catalog["catalog_hash"]

	# What an agent compiles against.
	for key in ("schema_version", "capabilities", "archetypes", "country_packs", "scales"):
		changed = dict(catalog, **{key: "something else"})
		assert catalog_hash(changed) != catalog["catalog_hash"], key

	# What differs between two sites running the same app versions, and so must
	# not move the hash.
	for key in ("installed_apps", "compatibility", "unavailable_providers"):
		assert catalog_hash(dict(catalog, **{key: "anything else"})) == catalog["catalog_hash"], key
