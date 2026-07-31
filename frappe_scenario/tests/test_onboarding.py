# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Onboarding state, installation, and first-login routing."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import frappe
import pytest

from frappe_scenario import install
from frappe_scenario import onboarding as login_integration
from frappe_scenario.core import onboarding

pytestmark = pytest.mark.pure


@pytest.fixture(autouse=True)
def plain_translations(monkeypatch):
	"""Keep pure state tests independent from Frappe's site translation cache."""
	monkeypatch.setattr(onboarding, "_", lambda message: message)

	def throw(message, exc=frappe.ValidationError, **kwargs):
		raise exc(message)

	monkeypatch.setattr(onboarding.frappe, "throw", throw)


class FakeOnboarding:
	def __init__(self, **values):
		self.initialized_on = None
		self.status = onboarding.NEEDS_PREREQUISITES
		self.state_version = 0
		self.initial_route_pending = 1
		self.completed_on = None
		self.saved = 0
		for key, value in values.items():
			setattr(self, key, value)

	def set(self, fieldname, value):
		setattr(self, fieldname, value)

	def save(self, *, ignore_permissions=False):
		assert ignore_permissions
		self.saved += 1
		return self

	def as_dict(self):
		return dict(self.__dict__)


def _report(*, blocking=0, installed=True, complete=True, companies=True, configurable_key=None):
	findings = []
	if configurable_key:
		findings.append({"key": configurable_key, "classification": "configurable"})
	return {
		"summary": {"blocking": blocking},
		"erpnext": {"installed": installed},
		"setup": {"complete": complete},
		"companies": [{"name": "Example"}] if companies else [],
		"findings": findings,
	}


@pytest.mark.parametrize(
	("report", "expected"),
	[
		(_report(blocking=1), onboarding.NEEDS_PREREQUISITES),
		(_report(installed=False), onboarding.NEEDS_SETUP),
		(_report(complete=False), onboarding.NEEDS_SETUP),
		(_report(companies=False), onboarding.NEEDS_SETUP),
		(_report(configurable_key="global_defaults"), onboarding.NEEDS_SETUP),
		(_report(), onboarding.NEEDS_SCENARIO),
	],
)
def test_initial_state_comes_only_from_preflight(report, expected):
	assert onboarding.initial_state(report) == expected


def test_after_install_ensures_onboarding_and_learning_catalog(monkeypatch):
	calls = []
	monkeypatch.setattr(onboarding, "ensure_onboarding", lambda: calls.append("ensure"))
	monkeypatch.setattr(
		"frappe_scenario.core.learning.sync_learning_paths",
		lambda: calls.append("learning"),
	)

	install.after_install()

	assert calls == ["ensure", "learning"]


def test_ensure_onboarding_initializes_once_and_preserves_resumable_state(monkeypatch):
	doc = FakeOnboarding()
	monkeypatch.setattr(onboarding.frappe, "get_single", lambda doctype: doc)
	monkeypatch.setattr(onboarding, "now_datetime", lambda: "2026-07-31 09:00:00")

	first = onboarding.ensure_onboarding(report=_report())
	assert first.status == onboarding.NEEDS_SCENARIO
	assert first.state_version == 1
	assert first.initial_route_pending == 1
	assert json.loads(first.progress)["current_state"] == onboarding.NEEDS_SCENARIO
	assert first.saved == 1

	first.intent = "Learn ERPNext"
	second = onboarding.ensure_onboarding(report=_report(blocking=1))
	assert second is first
	assert second.status == onboarding.NEEDS_SCENARIO
	assert second.intent == "Learn ERPNext"
	assert second.saved == 1


def test_state_machine_accepts_forward_progress_and_optimistic_version(monkeypatch):
	doc = FakeOnboarding(status=onboarding.NEEDS_SETUP, state_version=4)
	monkeypatch.setattr(onboarding.frappe, "get_single", lambda doctype: doc)

	updated = onboarding.transition_onboarding(
		onboarding.NEEDS_SCENARIO,
		updates={"intent": "Quick Demo", "setup_choices": {"country": "Kuwait"}},
		expected_version=4,
	)

	assert updated.status == onboarding.NEEDS_SCENARIO
	assert updated.state_version == 5
	assert updated.intent == "Quick Demo"
	assert json.loads(updated.setup_choices) == {"country": "Kuwait"}
	assert updated.saved == 1


def test_prerequisites_can_resolve_directly_to_scenario_on_a_configured_site(monkeypatch):
	doc = FakeOnboarding(status=onboarding.NEEDS_PREREQUISITES, state_version=1)
	monkeypatch.setattr(onboarding.frappe, "get_single", lambda doctype: doc)

	onboarding.transition_onboarding(onboarding.NEEDS_SCENARIO, expected_version=1)

	assert doc.status == onboarding.NEEDS_SCENARIO
	assert doc.state_version == 2


def test_state_machine_rejects_skips_stale_writes_and_unknown_fields(monkeypatch):
	doc = FakeOnboarding(status=onboarding.NEEDS_SETUP, state_version=4)
	monkeypatch.setattr(onboarding.frappe, "get_single", lambda doctype: doc)

	with pytest.raises(frappe.ValidationError, match="Cannot move"):
		onboarding.transition_onboarding(onboarding.GENERATING, expected_version=4)
	with pytest.raises(frappe.TimestampMismatchError, match="another session"):
		onboarding.transition_onboarding(onboarding.NEEDS_SCENARIO, expected_version=3)
	with pytest.raises(frappe.ValidationError, match="cannot be updated"):
		onboarding.transition_onboarding(
			onboarding.NEEDS_SETUP,
			updates={"status": onboarding.READY},
			expected_version=4,
		)
	with pytest.raises(frappe.ValidationError, match="JSON object"):
		onboarding.transition_onboarding(
			onboarding.NEEDS_SETUP,
			updates=["not", "an", "object"],
			expected_version=4,
		)


def test_ready_sets_completion_and_has_no_implicit_outbound_transition(monkeypatch):
	doc = FakeOnboarding(status=onboarding.GENERATING, state_version=8)
	monkeypatch.setattr(onboarding.frappe, "get_single", lambda doctype: doc)
	monkeypatch.setattr(onboarding, "now_datetime", lambda: "2026-07-31 09:30:00")

	onboarding.transition_onboarding(onboarding.READY, expected_version=8)
	assert doc.completed_on == "2026-07-31 09:30:00"

	with pytest.raises(frappe.ValidationError, match="Cannot move"):
		onboarding.transition_onboarding(onboarding.NEEDS_SCENARIO, expected_version=9)


class FakeCache:
	def __init__(self):
		self.values = {}

	def hset(self, namespace, key, value):
		self.values[(namespace, key)] = value


def _patch_login(monkeypatch, doc, *, roles):
	cache = FakeCache()
	monkeypatch.setattr(login_integration.frappe, "session", SimpleNamespace(user="Guest"))
	monkeypatch.setattr(login_integration.frappe, "get_roles", lambda user: list(roles))
	monkeypatch.setattr(
		login_integration.frappe,
		"db",
		SimpleNamespace(exists=lambda doctype, name: True),
	)
	monkeypatch.setattr(login_integration.frappe, "get_single", lambda doctype: doc)
	monkeypatch.setattr(login_integration.frappe, "cache", cache)
	monkeypatch.setattr(login_integration.frappe, "log_error", lambda **kwargs: None)
	monkeypatch.setattr(login_integration, "now_datetime", lambda: "2026-07-31 10:00:00")
	return cache


def test_first_system_manager_login_gets_one_shot_onboarding_route(monkeypatch):
	doc = FakeOnboarding(status=onboarding.NEEDS_SCENARIO, initial_route_pending=1)
	cache = _patch_login(monkeypatch, doc, roles={"System Manager"})
	manager = SimpleNamespace(user="administrator@example.test")

	login_integration.on_login(manager)

	assert cache.values[("redirect_after_login", manager.user)] == onboarding.ROUTE
	assert doc.initial_route_pending == 0
	assert doc.first_routed_user == manager.user
	assert doc.first_routed_on == "2026-07-31 10:00:00"
	assert doc.saved == 1

	login_integration.on_login(manager)
	assert doc.saved == 1


@pytest.mark.parametrize(
	("roles", "status", "pending"),
	[
		(set(), onboarding.NEEDS_SCENARIO, 1),
		({"System Manager"}, onboarding.READY, 1),
		({"System Manager"}, onboarding.NEEDS_SCENARIO, 0),
	],
)
def test_login_does_not_route_ineligible_or_completed_sessions(monkeypatch, roles, status, pending):
	doc = FakeOnboarding(status=status, initial_route_pending=pending)
	cache = _patch_login(monkeypatch, doc, roles=roles)

	login_integration.on_login(SimpleNamespace(user="user@example.test"))

	assert cache.values == {}
	assert doc.saved == 0


def test_routing_failure_never_blocks_system_manager_login(monkeypatch):
	logged = []
	monkeypatch.setattr(login_integration, "_route_on_login", lambda manager: 1 / 0)
	monkeypatch.setattr(
		login_integration.frappe,
		"log_error",
		lambda **kwargs: logged.append(kwargs),
	)
	monkeypatch.setattr(login_integration.frappe, "get_traceback", lambda: "traceback")

	login_integration.on_login(SimpleNamespace(user="administrator@example.test"))

	assert logged == [
		{
			"title": "Frappe Scenario onboarding route failed",
			"message": "traceback",
		}
	]


def test_onboarding_doctype_is_single_and_system_manager_only():
	path = (
		Path(__file__).resolve().parents[1]
		/ "frappe_scenario"
		/ "doctype"
		/ "scenario_onboarding"
		/ "scenario_onboarding.json"
	)
	definition = json.loads(path.read_text(encoding="utf-8"))

	assert definition["issingle"] == 1
	assert definition["permissions"] == [{"read": 1, "role": "System Manager", "write": 1}]
	status = next(field for field in definition["fields"] if field["fieldname"] == "status")
	assert tuple(status["options"].splitlines()) == onboarding.STATES
