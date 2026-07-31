# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Deterministic preview and generated quality gates."""

from __future__ import annotations

import copy

import pytest

from frappe_scenario.core.quality import BLOCKED, READY, REVIEW, assess_generated, assess_preview
from frappe_scenario.core.realism_preview import representative_preview

pytestmark = pytest.mark.pure


def _preview():
	return representative_preview(
		{
			"archetype": "hvac_distribution",
			"country": "Kuwait",
			"currency": "KWD",
			"preview_variation": 0,
		}
	)


def test_realistic_preview_passes_every_quality_dimension():
	report = assess_preview(_preview())

	assert report["status"] == READY
	assert report["passed"]
	assert report["overall_score"] == 100
	assert set(report["scores"]) == {
		"naming",
		"regional_consistency",
		"linkage",
		"accounting",
		"continuity",
	}


def test_structural_preview_error_blocks_generation():
	samples = copy.deepcopy(_preview())
	samples["parties"][0]["email"] = "person@real-domain.com"

	report = assess_preview(samples)

	assert report["status"] == BLOCKED
	assert not report["passed"]
	assert any(finding["category"] == "regional_consistency" for finding in report["findings"])


def test_low_continuity_requires_confirmation_without_blocking():
	samples = copy.deepcopy(_preview())
	samples["transaction_stories"][0]["lifecycle"] = ["Sales Invoice"]

	report = assess_preview(samples)

	assert report["status"] == REVIEW
	assert report["passed"]
	assert report["confirmation_required"]


def test_generated_accounting_error_is_a_blocking_quality_finding():
	report = assess_generated(
		specification={"scenario": {"history_months": 1}},
		capabilities={},
		validation={
			"issues": [
				{
					"rule": "core.gl_balanced",
					"severity": "error",
					"message": "Voucher is not balanced.",
				}
			]
		},
	)

	assert report["status"] == BLOCKED
	assert report["scores"]["accounting"] < 100


def test_generated_linkage_and_continuity_are_scored():
	report = assess_generated(
		specification={"scenario": {"history_months": 3}},
		capabilities={
			"erpnext.selling.sales_invoices": [
				{"name": "SINV-1", "posting_date": "2026-07-01", "channel": "credit"}
			],
			"erpnext.buying.purchase_invoices": [{"name": "PINV-1", "posting_date": "2026-07-02"}],
		},
		validation={"issues": []},
	)

	assert report["status"] == BLOCKED
	assert report["scores"]["linkage"] < 100
	assert report["scores"]["continuity"] < 100
