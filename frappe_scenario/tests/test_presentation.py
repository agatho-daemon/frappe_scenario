# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Presentation Demo preset, identity, bilingual copy, and publication contract."""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest

from frappe_scenario.core.presentation import (
	_bilingual_copy,
	_identity,
	_metrics,
	_tour,
	compile_presentation_specification,
)
from frappe_scenario.core.specification import validate_schema

pytestmark = pytest.mark.pure


def _choices() -> dict:
	return {
		"intent": "Presentation Demo",
		"archetype": "hvac_distribution",
		"depth": "Everyday Business",
		"company_strategy": "initialize_if_needed",
		"country": "Kuwait",
		"language": "en",
		"timezone": "Asia/Kuwait",
		"currency": "KWD",
		"company_name": "Wasaq Climate Solutions",
		"company_abbr": "WCS",
		"chart_template": "Standard",
		"account_numbering": "With Numbers",
		"fiscal_year_start": "2026-01-01",
		"perpetual_inventory": True,
		"valuation_method": "Moving Average",
		"warehouse_name": "Main Stores",
		"cost_center_name": "Main",
		"scale": "small",
		"history_months": 2,
		"preview_variation": 0,
	}


def test_presentation_compilation_is_deterministic_polished_and_schema_valid():
	anchor = datetime.date(2026, 7, 31)
	first = compile_presentation_specification(_choices(), anchor_date=anchor)
	second = compile_presentation_specification(_choices(), anchor_date=anchor)

	assert first == second
	assert validate_schema(first) == []
	assert first["scenario"]["intent"] == "Presentation Demo"
	assert first["presentation"] == {
		"include_logo": True,
		"bilingual": True,
		"guided_tour": True,
		"identity_style": "Modern",
	}
	assert first["operations"]["returns"] < 0.08
	assert first["accounting"]["overdue_receivables"] < 0.18


def test_identity_logo_copy_metrics_and_tour_are_stable_and_evidence_backed():
	scenario = {
		"archetype": "hvac_distribution",
		"seed": 7,
		"locale": {"primary": "ar_AA", "secondary": "en_US"},
	}
	identity = _identity("Wasaq Climate Solutions", scenario, {"include_logo": True})
	assert identity == _identity("Wasaq Climate Solutions", scenario, {"include_logo": True})
	assert identity["initials"] == "WCS"
	assert identity["logo_svg"].startswith("<svg")
	assert "<script" not in identity["logo_svg"]

	copy = _bilingual_copy(scenario, True)
	assert copy["primary_locale"] == "ar_AA"
	assert copy["primary"] != copy["secondary"]

	capabilities = {
		"erpnext.parties.customers": [{"name": "Customer One"}],
		"erpnext.catalog.items": [{"name": "ITEM-1"}, {"name": "ITEM-2"}],
		"erpnext.selling.sales_invoices": [{"name": "SINV-1", "grand_total": 12.345}],
		"erpnext.accounts.customer_payments": [{"name": "PAY-1"}],
	}
	metrics = {entry["key"]: entry for entry in _metrics(capabilities, "KWD")}
	assert metrics["revenue"]["value"] == 12.35
	assert metrics["items"]["value"] == 2
	assert all(step["evidence_count"] > 0 for step in _tour(capabilities))


def test_presentation_page_is_a_system_manager_desk_surface():
	path = (
		Path(__file__).resolve().parents[1]
		/ "frappe_scenario"
		/ "page"
		/ "scenario_presentation"
		/ "scenario_presentation.json"
	)
	payload = json.loads(path.read_text())
	assert payload["name"] == "scenario-presentation"
	assert payload["roles"] == [{"role": "System Manager"}]
