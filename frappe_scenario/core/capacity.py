# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Conservative resource forecasts for review before generation."""

from __future__ import annotations

import math
from typing import Any

from frappe_scenario.core.lifecycle import forecast_specification_lifecycle
from frappe_scenario.core.scale import get_scale_profile


def estimate_resources(specification: dict[str, Any], provider_records: int) -> dict[str, Any]:
	"""Estimate durable documents, child/ledger rows, storage, and controller runtime."""
	lifecycle = forecast_specification_lifecycle(specification)
	transactions = sum(
		lifecycle[key]
		for key in (
			"sales_orders",
			"delivery_notes",
			"sales_invoices",
			"customer_payments",
			"purchase_orders",
			"purchase_receipts",
			"purchase_invoices",
			"supplier_payments",
		)
	)
	provider_options = specification.get("providers") or {}
	line_ranges = [
		(provider_options.get("erpnext.selling") or {}).get("lines_per_order") or [1, 4],
		(provider_options.get("erpnext.buying") or {}).get("lines_per_order") or [1, 5],
	]
	average_lines = sum((float(bounds[0]) + float(bounds[1])) / 2 for bounds in line_ranges) / 2
	# Transaction children, GL rows, stock ledger rows, and payment references are
	# deliberately estimated conservatively. They are database rows, not manifest documents.
	database_rows = math.ceil(provider_records + transactions * (average_lines + 4.5))
	storage_mb = database_rows * 2.75 / 1024
	minimum_minutes = max(1, math.floor(provider_records / 900))
	maximum_minutes = max(2, math.ceil(provider_records / 180))
	profile = get_scale_profile(specification["scenario"]["scale"])
	target = profile["record_target"]
	warnings: list[str] = []
	if provider_records < target["minimum"] or provider_records > target["maximum"]:
		warnings.append(
			f"The resolved provider plan estimates {provider_records:,} documents, outside the "
			f"{target['minimum']:,}-{target['maximum']:,} target for this scale."
		)
	if profile.get("confirmation_required"):
		warnings.append(
			"Large generation may create tens of thousands of documents and should run on a "
			"disposable site with a long worker available."
		)
	return {
		"documents": provider_records,
		"database_rows": database_rows,
		"storage_mb": {
			"minimum": round(storage_mb * 0.7, 1),
			"typical": round(storage_mb, 1),
			"maximum": round(storage_mb * 1.5, 1),
		},
		"runtime_minutes": {"minimum": minimum_minutes, "maximum": maximum_minutes},
		"history_months": specification["scenario"]["history_months"],
		"lifecycle": lifecycle,
		"confirmation_required": bool(profile.get("confirmation_required")),
		"warnings": warnings,
	}
