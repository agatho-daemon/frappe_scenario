# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Login integration for the onboarding workflow."""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import now_datetime

from frappe_scenario.core.onboarding import DOCTYPE, READY, ROUTE


def on_login(login_manager: Any | None = None) -> None:
	"""Route the first System Manager login to incomplete onboarding."""
	try:
		_route_on_login(login_manager)
	except Exception:
		# Onboarding must never lock an administrator out of Desk.
		try:
			frappe.log_error(
				title="Frappe Scenario onboarding route failed",
				message=frappe.get_traceback(),
			)
		except Exception:
			return


def _route_on_login(login_manager: Any | None = None) -> None:
	user = getattr(login_manager, "user", None) or getattr(frappe.session, "user", None)
	if not user or user == "Guest" or "System Manager" not in frappe.get_roles(user):
		return
	if not frappe.db.exists("DocType", DOCTYPE):
		return

	doc = frappe.get_single(DOCTYPE)
	if not doc.initial_route_pending or doc.status == READY:
		return

	frappe.cache.hset("redirect_after_login", user, ROUTE)
	doc.initial_route_pending = 0
	doc.first_routed_user = user
	doc.first_routed_on = now_datetime()
	doc.save(ignore_permissions=True)
