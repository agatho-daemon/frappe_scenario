# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Manifest bookkeeping: the record of what a run owns."""

import pytest

from frappe_scenario.core.engine import _manifest_filename
from frappe_scenario.core.manifest import Manifest, ManifestRecord

pytestmark = pytest.mark.pure


def test_each_run_gets_a_distinct_physical_manifest_filename():
	assert _manifest_filename("SCN-RUN-1") != _manifest_filename("SCN-RUN-2")
	assert _manifest_filename("SCN-RUN-1").endswith("-manifest.jsonl")


def _record(doctype: str, name: str, provider: str = "erpnext.selling", **kwargs) -> ManifestRecord:
	return ManifestRecord(doctype=doctype, name=name, provider=provider, **kwargs)


def test_append_assigns_increasing_sequence_numbers():
	manifest = Manifest()
	first = manifest.append(_record("Customer", "CUST-1"))
	second = manifest.append(_record("Customer", "CUST-2"))
	assert first.sequence < second.sequence
	assert len(manifest) == 2


def test_truncate_after_drops_only_later_records():
	manifest = Manifest()
	kept = manifest.append(_record("Customer", "CUST-1"))
	manifest.append(_record("Customer", "CUST-2"))
	manifest.append(_record("Customer", "CUST-3"))

	removed = manifest.truncate_after(kept.sequence)

	assert [record.name for record in manifest] == ["CUST-1"]
	assert [record.name for record in removed] == ["CUST-2", "CUST-3"]


def test_created_and_modified_are_separated():
	manifest = Manifest()
	manifest.append(_record("Customer", "CUST-1"))
	manifest.append(_record("System Settings", "System Settings", operation="modified"))

	assert [record.name for record in manifest.created()] == ["CUST-1"]
	assert [record.name for record in manifest.modified()] == ["System Settings"]


def test_records_are_grouped_by_provider_and_capability():
	manifest = Manifest()
	manifest.append(_record("Customer", "CUST-1", capability="erpnext.parties.customers"))
	manifest.append(_record("Item", "ITEM-1", provider="erpnext.catalog", capability="erpnext.catalog.items"))

	assert [record.name for record in manifest.for_provider("erpnext.catalog")] == ["ITEM-1"]
	assert [record.name for record in manifest.for_capability("erpnext.parties.customers")] == ["CUST-1"]
	assert manifest.counts_by_doctype() == {"Customer": 1, "Item": 1}
	assert manifest.counts_by_provider() == {"erpnext.selling": 1, "erpnext.catalog": 1}


def test_a_manifest_survives_a_jsonl_round_trip():
	manifest = Manifest()
	manifest.append(_record("Customer", "CUST-1", docstatus=1, dependencies=["Company/ACME"]))
	manifest.append(
		_record(
			"System Settings", "System Settings", operation="modified", original_values={"time_zone": "UTC"}
		)
	)

	restored = Manifest.from_jsonl(manifest.to_jsonl())

	assert [record.as_dict() for record in restored] == [record.as_dict() for record in manifest]


def test_reference_identifies_a_record_across_doctypes():
	assert _record("Customer", "CUST-1").reference == "Customer/CUST-1"
