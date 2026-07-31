# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Scale profiles and validation result aggregation."""

import pytest

from frappe_scenario.core.capacity import estimate_resources
from frappe_scenario.core.errors import ScenarioError
from frappe_scenario.core.lifecycle import (
	OPERATIONAL_DEPTHS,
	derive_lifecycle_counts,
	forecast_specification_lifecycle,
	get_depth_profile,
)
from frappe_scenario.core.scale import describe_scale_profiles, get_scale_profile
from frappe_scenario.core.specification import resolve_specification
from frappe_scenario.core.validation import ValidationResult
from frappe_scenario.providers.erpnext_buying import _activity_weights as supplier_activity_weights
from frappe_scenario.providers.erpnext_selling import _activity_weights as customer_activity_weights

pytestmark = pytest.mark.pure


def test_every_advertised_profile_can_be_fetched():
	for profile in describe_scale_profiles():
		assert get_scale_profile(profile["id"])


def test_profiles_grow_monotonically():
	names = ["smoke", "small", "medium", "large"]
	profiles = [get_scale_profile(name) for name in names]
	customers = [profile["parties"]["customers"] for profile in profiles]
	months = [profile["history_months"] for profile in profiles]
	assert customers == sorted(customers)
	assert months == sorted(months)
	assert len(set(customers)) == len(customers)


def test_describe_flattens_the_headline_counts_for_the_cli():
	described = {profile["id"]: profile for profile in describe_scale_profiles()}
	assert described["smoke"]["customers"] == get_scale_profile("smoke")["parties"]["customers"]
	assert described["smoke"]["description"]
	assert described["smoke"]["record_target"]["typical"] == 150


def test_medium_and_large_obey_the_advertised_history_windows():
	medium = get_scale_profile("medium")
	large = get_scale_profile("large")

	assert medium["history_range"] == [12, 24]
	assert 12 <= medium["history_months"] <= 24
	assert large["history_range"] == [24, 36]
	assert 24 <= large["history_months"] <= 36
	assert large["confirmation_required"]


def test_scale_forecast_is_ratio_driven_and_seasonal():
	resolved, _ = resolve_specification(
		{
			"schema_version": "1.0",
			"scenario": {
				"archetype": "hvac_distribution",
				"country": "Kuwait",
				"scale": "medium",
				"anchor_date": "2026-07-31",
				"seed": 7,
			},
		}
	)
	forecast = forecast_specification_lifecycle(resolved)

	assert forecast["sales_activities"] > (
		resolved["operations"]["sales_orders_per_month"] * resolved["scenario"]["history_months"]
	)
	assert forecast["sales_orders"] < forecast["sales_activities"]  # cash activity is invoiced directly
	assert forecast["customer_payments"] < forecast["sales_invoices"]
	assert forecast["supplier_payments"] < forecast["purchase_invoices"]


def test_large_resource_forecast_requires_confirmation_and_estimates_rows():
	resolved, _ = resolve_specification(
		{
			"schema_version": "1.0",
			"scenario": {
				"archetype": "hvac_distribution",
				"country": "Kuwait",
				"scale": "large",
				"anchor_date": "2026-07-31",
				"seed": 7,
			},
		}
	)
	estimate = estimate_resources(resolved, 25000)

	assert estimate["confirmation_required"]
	assert estimate["database_rows"] > estimate["documents"]
	assert estimate["storage_mb"]["minimum"] < estimate["storage_mb"]["maximum"]
	assert estimate["runtime_minutes"]["minimum"] < estimate["runtime_minutes"]["maximum"]
	assert estimate["warnings"]


def test_concentration_weights_are_bounded_monotonic_and_shared_by_buying_and_selling():
	assert customer_activity_weights(5, 0.25) == supplier_activity_weights(5, 0.25)
	weights = customer_activity_weights(5, 0.25)
	assert weights == sorted(weights, reverse=True)
	assert weights[-1] == 1
	assert customer_activity_weights(3, 0) == [1, 1, 1]


def test_depth_changes_lifecycle_coverage_without_changing_activity_volume():
	plans = [
		derive_lifecycle_counts(sales_activities=100, purchase_orders=50, depth=depth)
		for depth in OPERATIONAL_DEPTHS
	]

	assert {plan["sales_orders"] for plan in plans} == {100}
	assert {plan["purchase_orders"] for plan in plans} == {50}
	assert [plan["sales_invoices"] for plan in plans] == sorted(plan["sales_invoices"] for plan in plans)
	assert [plan["customer_payments"] for plan in plans] == sorted(
		plan["customer_payments"] for plan in plans
	)


def test_cash_sales_become_invoices_without_inflating_sales_orders():
	plan = derive_lifecycle_counts(
		sales_activities=100,
		purchase_orders=0,
		depth="Everyday Business",
		cash_sales_ratio=0.2,
	)

	assert plan["sales_orders"] == 80
	assert plan["cash_sales_invoices"] == 20
	assert plan["sales_invoices"] >= 20


def test_depth_profile_is_defensive_and_unknown_depth_is_rejected():
	profile = get_depth_profile("Essentials")
	profile["selling"]["delivery_ratio"] = 0

	assert get_depth_profile("Essentials")["selling"]["delivery_ratio"] == 0.8
	with pytest.raises(ScenarioError):
		get_depth_profile("Exhaustive")


def test_an_unknown_scale_is_refused():
	with pytest.raises(ScenarioError):
		get_scale_profile("enormous")


def test_a_result_with_only_warnings_still_passes():
	result = ValidationResult()
	result.warning("selling.concentration", "One customer takes most of the revenue.")
	result.info("selling.count", "8 invoices.")
	assert result.passed
	assert result.counts() == {"error": 0, "warning": 1, "info": 1}


def test_a_single_error_fails_the_result():
	result = ValidationResult()
	result.error("stock.valuation", "Bin and ledger disagree.")
	assert not result.passed
	assert [issue.rule for issue in result.errors] == ["stock.valuation"]


def test_results_combine_without_losing_issues():
	left = ValidationResult()
	left.error("a", "first")
	right = ValidationResult()
	right.warning("b", "second")
	left.extend(right)
	assert len(left.issues) == 2


def test_a_skipped_rule_is_removed_from_the_result():
	result = ValidationResult()
	result.error("stock.valuation", "Bin and ledger disagree.")
	result.warning("selling.concentration", "Concentrated.")

	filtered = result.filtered({"stock.valuation"})

	assert filtered.passed
	assert [issue.rule for issue in filtered.issues] == ["selling.concentration"]
	# Filtering must not mutate the original.
	assert not result.passed
