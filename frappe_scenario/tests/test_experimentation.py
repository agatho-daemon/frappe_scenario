# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt

import pytest

from frappe_scenario.core.experimentation import _change_counts, _diff


pytestmark = pytest.mark.pure


def test_checkpoint_diff_reports_changed_deleted_and_reappeared_records():
	before = {
		"records": {
			"Customer/C-1": {"values": {"customer_name": "Before"}, "docstatus": 0},
			"Item/I-1": {"values": {"item_name": "Item"}, "docstatus": 0},
			"Lead/L-1": {"missing": True},
		}
	}
	after = {
		"records": {
			"Customer/C-1": {"values": {"customer_name": "After"}, "docstatus": 0},
			"Item/I-1": {"missing": True},
			"Lead/L-1": {"values": {"first_name": "Now here"}, "docstatus": 0},
		}
	}

	changes = _diff(before, after)

	assert changes == [
		{"reference": "Customer/C-1", "status": "Changed", "fields": ["customer_name"]},
		{"reference": "Item/I-1", "status": "Deleted"},
		{"reference": "Lead/L-1", "status": "Reappeared"},
	]
	assert _change_counts(changes) == {"Changed": 1, "Deleted": 1, "Reappeared": 1}


def test_checkpoint_diff_reports_docstatus_changes_explicitly():
	before = {"records": {"Sales Order/SO-1": {"values": {"status": "To Deliver"}, "docstatus": 1}}}
	after = {"records": {"Sales Order/SO-1": {"values": {"status": "Cancelled"}, "docstatus": 2}}}

	assert _diff(before, after)[0]["fields"][0] == "docstatus"
