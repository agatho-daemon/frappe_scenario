# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Release artifact, installed-schema, permission, and secret-boundary gates."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from frappe_scenario import commands
from frappe_scenario.core.release import EXIT_RELEASE_BLOCKED, source_audit

REPOSITORY = Path(__file__).resolve().parents[2]


@pytest.mark.pure
def test_source_release_audit_passes_for_the_checkout():
	checks = source_audit(REPOSITORY)
	assert checks
	assert not [entry for entry in checks if entry["status"] == "failed"]
	assert {entry["id"] for entry in checks} >= {
		"artifact.local_plans_ignored",
		"artifact.no_local_plans_in_package",
		"security.doctype_permissions",
		"security.credential_storage",
		"upgrade.patch_sections",
		"upgrade.versioned_schema",
		"documentation.public_surfaces",
	}


@pytest.mark.pure
def test_local_plans_are_not_inside_the_package_or_git_release_inputs():
	assert not list((REPOSITORY / "frappe_scenario").rglob("SCENARIO_PLAN.md"))
	assert not list((REPOSITORY / "frappe_scenario").rglob("DECISIONS.md"))
	ignored = (REPOSITORY / ".gitignore").read_text(encoding="utf-8")
	assert "/SCENARIO_PLAN.md" in ignored
	assert "/DECISIONS.md" in ignored


@pytest.mark.pure
def test_release_audit_command_and_exit_code_are_stable():
	assert "release-audit" in commands.scenario.commands
	assert EXIT_RELEASE_BLOCKED == 60


@pytest.mark.frappe_site
def test_installed_release_audit_is_ready_and_secret_free(frappe_site):
	from frappe_scenario.core.release import site_audit

	payload = site_audit(REPOSITORY)
	assert payload["format"] == "frappe-scenario-release-audit-1"
	assert payload["site"] == frappe_site
	assert payload["ready"], [entry for entry in payload["checks"] if entry["status"] == "failed"]
	assert payload["exit_code"] == 0
	serialized = json.dumps(payload).lower()
	assert "api_key" not in serialized
	assert "authorization" not in serialized
	assert "bearer " not in serialized


@pytest.mark.frappe_site
def test_installed_scenario_doctypes_remain_system_manager_only(frappe_site):
	import frappe

	for path in (REPOSITORY / "frappe_scenario" / "frappe_scenario" / "doctype").glob("*/*.json"):
		definition = json.loads(path.read_text(encoding="utf-8"))
		meta = frappe.get_meta(definition["name"])
		roles = {permission.role for permission in meta.permissions}
		assert not roles if definition.get("istable") else roles == {"System Manager"}
