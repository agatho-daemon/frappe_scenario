# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Frappe/ERPNext v16 adapter."""

from __future__ import annotations

from frappe_scenario.compatibility.base import CompatibilityAdapter


class V16Adapter(CompatibilityAdapter):
	id = "v16"

	# v16 still resolves mappers from the controller module; the dedicated
	# ``mapper`` module is checked second so a partial backport keeps working.
	mapper_module_order = ("{doctype_module}", "mapper")
