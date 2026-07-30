# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Site safety.

Generation writes a large amount of synthetic business data through real
controllers. The platform therefore refuses to run anywhere that is not an
explicitly marked development target.
"""

from __future__ import annotations

from typing import Any

import frappe

from frappe_scenario.core.errors import SafetyError

DISPOSABLE_FLAG = "frappe_scenario_disposable"
OVERRIDE_FLAG = "frappe_scenario_allow_non_disposable"


def site_safety_report() -> dict[str, Any]:
	"""Read-only description of the current site's safety posture."""
	conf = frappe.conf or {}
	return {
		"site": frappe.local.site,
		"developer_mode": bool(conf.get("developer_mode")),
		"disposable": bool(conf.get(DISPOSABLE_FLAG)),
		"non_disposable_override_configured": bool(conf.get(OVERRIDE_FLAG)),
		"maintenance_mode": bool(conf.get("maintenance_mode")),
		"generation_allowed": _blockers(allow_non_disposable=False) == [],
	}


def _blockers(*, allow_non_disposable: bool) -> list[dict[str, str]]:
	conf = frappe.conf or {}
	blockers: list[dict[str, str]] = []

	if not conf.get("developer_mode"):
		blockers.append(
			{
				"check": "developer_mode",
				"message": "developer_mode is not enabled on this site.",
				"remediation": f"bench --site {frappe.local.site} set-config developer_mode 1",
			}
		)

	if conf.get("maintenance_mode"):
		blockers.append(
			{
				"check": "maintenance_mode",
				"message": "The site is in maintenance mode, which indicates a managed deployment.",
				"remediation": "Run scenarios on a disposable development site instead.",
			}
		)

	if not conf.get(DISPOSABLE_FLAG):
		if not allow_non_disposable:
			blockers.append(
				{
					"check": "disposable_site",
					"message": (
						f"Site config {DISPOSABLE_FLAG!r} is not set. Scenario generation is "
						"restricted to disposable development sites."
					),
					"remediation": (f"bench --site {frappe.local.site} set-config {DISPOSABLE_FLAG} 1"),
				}
			)
		elif not conf.get(OVERRIDE_FLAG):
			blockers.append(
				{
					"check": "non_disposable_override",
					"message": (
						"A non-disposable run was requested but the site does not configure "
						f"{OVERRIDE_FLAG!r}."
					),
					"remediation": f"bench --site {frappe.local.site} set-config {OVERRIDE_FLAG} 1",
				}
			)

	return blockers


def assert_safe_to_generate(*, allow_non_disposable: bool = False) -> None:
	"""Raise :class:`SafetyError` unless this site may be written to."""
	blockers = _blockers(allow_non_disposable=allow_non_disposable)
	if blockers:
		raise SafetyError(
			"This site is not an approved scenario target.",
			phase="safety",
			details={"site": frappe.local.site, "blockers": blockers},
		)
