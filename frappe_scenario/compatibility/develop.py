# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Frappe/ERPNext develop (dev-17) adapter.

The develop branch moved ERPNext document mappers out of the controller modules
into a dedicated ``mapper`` module per DocType, for example
``erpnext.selling.doctype.sales_order.mapper.make_delivery_note``.
"""

from __future__ import annotations

from frappe_scenario.compatibility.base import CompatibilityAdapter


class DevelopAdapter(CompatibilityAdapter):
	id = "develop"

	# Prefer the dedicated mapper module, fall back to the controller module.
	mapper_module_order = ("mapper", "{doctype_module}")
