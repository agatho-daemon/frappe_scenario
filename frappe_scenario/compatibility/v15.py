# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Frappe/ERPNext v15 adapter."""

from __future__ import annotations

from frappe_scenario.compatibility.base import CompatibilityAdapter


class V15Adapter(CompatibilityAdapter):
	id = "v15"

	# v15 keeps document mappers beside the controller module.
	mapper_module_order = ("{doctype_module}", "mapper")
