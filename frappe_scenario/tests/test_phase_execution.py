# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Provider-boundary execution metadata."""

import pytest

from frappe_scenario.core.engine import phase_input_fingerprint, phase_output_fingerprint

pytestmark = pytest.mark.pure


def test_phase_input_fingerprint_is_stable_across_mapping_order():
	first = phase_input_fingerprint(
		provider_id="erpnext.parties",
		provider_version="1.2",
		specification_hash_value="specification",
		capabilities={"second": {"b": 2, "a": 1}, "first": True},
	)
	second = phase_input_fingerprint(
		provider_id="erpnext.parties",
		provider_version="1.2",
		specification_hash_value="specification",
		capabilities={"first": True, "second": {"a": 1, "b": 2}},
	)

	assert first == second
	assert len(first) == 64


def test_phase_input_fingerprint_changes_with_provider_inputs():
	common = {
		"provider_id": "erpnext.parties",
		"provider_version": "1.2",
		"specification_hash_value": "specification",
	}

	assert phase_input_fingerprint(**common, capabilities={"company": "One"}) != (
		phase_input_fingerprint(**common, capabilities={"company": "Two"})
	)


def test_phase_output_fingerprint_covers_result_capabilities_and_manifest_slice():
	base = {
		"provider_id": "erpnext.parties",
		"result": {"summary": {"customers": 2}, "warnings": []},
		"capabilities": {"erpnext.parties.customers": ["A", "B"]},
		"records": [{"doctype": "Customer", "name": "A", "sequence": 3}],
	}
	fingerprint = phase_output_fingerprint(**base)

	assert fingerprint == phase_output_fingerprint(**base)
	assert fingerprint != phase_output_fingerprint(
		**{**base, "records": [{"doctype": "Customer", "name": "B", "sequence": 3}]}
	)
