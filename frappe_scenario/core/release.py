# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Read-only release gates for source artifacts and installed sites."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

RELEASE_AUDIT_FORMAT = "frappe-scenario-release-audit-1"
EXIT_RELEASE_BLOCKED = 60
SUPPORTED_MAJORS = {15, 16, 17}
LOCAL_ONLY_FILES = {"SCENARIO_PLAN.md", "DECISIONS.md"}
REQUIRED_DOCUMENTATION = {
	"Learn ERPNext",
	"Quick Demo",
	"Presentation Demo",
	"Developer and CI datasets",
	"Current boundaries",
}


def source_audit(root: str | Path | None = None) -> list[dict[str, Any]]:
	"""Inspect release inputs without invoking Git, package managers, or a network."""
	repository = Path(root) if root else Path(__file__).resolve().parents[2]
	checks: list[dict[str, Any]] = []
	gitignore = _read(repository / ".gitignore")
	ignored = {line.strip().lstrip("/") for line in gitignore.splitlines() if line.strip()}
	checks.append(
		check(
			"artifact.local_plans_ignored",
			LOCAL_ONLY_FILES <= ignored,
			"Local planning documents are excluded from release tracking.",
			{"required": sorted(LOCAL_ONLY_FILES), "ignored": sorted(LOCAL_ONLY_FILES & ignored)},
		)
	)
	package_root = repository / "frappe_scenario"
	packaged_local = sorted(path.name for path in package_root.rglob("*") if path.name in LOCAL_ONLY_FILES)
	checks.append(
		check(
			"artifact.no_local_plans_in_package",
			not packaged_local,
			"No local planning documents exist inside the importable package.",
			{"found": packaged_local},
		)
	)

	doctype_root = package_root / "frappe_scenario" / "doctype"
	doctype_files = sorted(doctype_root.glob("*/*.json"))
	permission_failures: list[str] = []
	for path in doctype_files:
		definition = json.loads(path.read_text(encoding="utf-8"))
		roles = {row.get("role") for row in definition.get("permissions") or []}
		permissions_valid = not roles if definition.get("istable") else roles == {"System Manager"}
		if not permissions_valid:
			permission_failures.append(definition.get("name") or path.parent.name)
	checks.append(
		check(
			"security.doctype_permissions",
			not permission_failures,
			"All scenario records are restricted to System Manager.",
			{"doctypes": len(doctype_files), "failures": permission_failures},
		)
	)

	ai_provider = json.loads(
		(doctype_root / "scenario_ai_provider" / "scenario_ai_provider.json").read_text(encoding="utf-8")
	)
	fields = {field["fieldname"]: field for field in ai_provider["fields"]}
	checks.append(
		check(
			"security.credential_storage",
			fields.get("credential", {}).get("fieldtype") == "Password",
			"AI credentials use Frappe encrypted Password storage.",
			{"fieldtype": fields.get("credential", {}).get("fieldtype")},
		)
	)

	patches = _read(package_root / "patches.txt")
	checks.append(
		check(
			"upgrade.patch_sections",
			"[pre_model_sync]" in patches and "[post_model_sync]" in patches,
			"Frappe migration patch sections are declared.",
		)
	)
	readme = _read(repository / "README.md")
	missing_docs = sorted(token for token in REQUIRED_DOCUMENTATION if token not in readme)
	checks.append(
		check(
			"documentation.public_surfaces",
			not missing_docs,
			"README distinguishes and documents the shipped product surfaces.",
			{"missing": missing_docs},
		)
	)
	schema = json.loads((package_root / "core" / "schema" / "scenario-1.0.json").read_text(encoding="utf-8"))
	checks.append(
		check(
			"upgrade.versioned_schema",
			schema.get("properties", {}).get("schema_version", {}).get("const") == "1.0",
			"The public specification is pinned to an explicit schema version.",
			{"schema_version": schema.get("properties", {}).get("schema_version", {}).get("const")},
		)
	)
	return checks


def site_audit(root: str | Path | None = None) -> dict[str, Any]:
	"""Return a secret-free readiness verdict for the connected Frappe site."""
	import frappe

	from frappe_scenario.compatibility import compatibility_level
	from frappe_scenario.core.safety import site_safety_report

	checks = source_audit(root)
	installed = set(frappe.get_installed_apps())
	checks.append(
		check(
			"site.required_apps",
			{"frappe", "erpnext", "frappe_scenario"} <= installed,
			"Frappe, ERPNext, and Frappe Scenario are installed.",
			{"installed": sorted(installed & {"frappe", "erpnext", "frappe_scenario"})},
		)
	)
	compatibility = compatibility_level()
	checks.append(
		check(
			"site.compatibility",
			compatibility["frappe_major"] in SUPPORTED_MAJORS
			and compatibility["erpnext_major"] in SUPPORTED_MAJORS,
			"Installed framework majors have a Frappe Scenario compatibility adapter.",
			compatibility,
		)
	)

	repository = Path(root) if root else Path(__file__).resolve().parents[2]
	doctype_root = repository / "frappe_scenario" / "frappe_scenario" / "doctype"
	required_doctypes = sorted(
		json.loads(path.read_text(encoding="utf-8")).get("name") for path in doctype_root.glob("*/*.json")
	)
	missing_doctypes = [name for name in required_doctypes if not frappe.db.exists("DocType", name)]
	checks.append(
		check(
			"site.schema_synced",
			not missing_doctypes,
			"Every shipped Scenario DocType is synchronized on the site.",
			{"doctypes": len(required_doctypes), "missing": missing_doctypes},
		)
	)
	credential_meta = frappe.get_meta("Scenario AI Provider").get_field("credential")
	checks.append(
		check(
			"site.credential_metadata",
			bool(credential_meta and credential_meta.fieldtype == "Password"),
			"Installed AI credential metadata remains encrypted and non-readable.",
			{"fieldtype": credential_meta.fieldtype if credential_meta else None},
		)
	)
	safety = site_safety_report()
	expected_allowed = bool(
		safety["developer_mode"] and safety["disposable"] and not safety.get("maintenance_mode")
	)
	checks.append(
		check(
			"site.safety_posture",
			safety["generation_allowed"] is expected_allowed,
			"Generation requires an explicit disposable development-site posture.",
			{
				"developer_mode": safety["developer_mode"],
				"disposable": safety["disposable"],
				"generation_allowed": safety["generation_allowed"],
			},
		)
	)
	failed = [entry for entry in checks if entry["status"] == "failed"]
	return {
		"format": RELEASE_AUDIT_FORMAT,
		"ready": not failed,
		"site": frappe.local.site,
		"compatibility": compatibility,
		"checks": checks,
		"counts": {"passed": len(checks) - len(failed), "failed": len(failed)},
		"exit_code": 0 if not failed else EXIT_RELEASE_BLOCKED,
	}


def check(
	check_id: str, passed: bool, message: str, evidence: dict[str, Any] | None = None
) -> dict[str, Any]:
	return {
		"id": check_id,
		"status": "passed" if passed else "failed",
		"message": message,
		"evidence": evidence or {},
	}


def _read(path: Path) -> str:
	return path.read_text(encoding="utf-8") if path.is_file() else ""
