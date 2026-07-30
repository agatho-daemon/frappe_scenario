# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Scale profiles and validation result aggregation."""

import pytest

from frappe_scenario.core.errors import ScenarioError
from frappe_scenario.core.scale import describe_scale_profiles, get_scale_profile
from frappe_scenario.core.validation import ValidationResult

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
