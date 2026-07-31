# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Pure contract tests for grounded tutor output."""

import json

import pytest

from frappe_scenario.ai.executor import AIExecutionError, AIHTTPResult
from frappe_scenario.ai.tutor import _parse_output

pytestmark = pytest.mark.pure


def _response(output):
	return AIHTTPResult(
		200,
		{
			"output": [
				{
					"type": "message",
					"content": [{"type": "output_text", "text": json.dumps(output)}],
				}
			]
		},
	)


def test_tutor_accepts_classified_claims_with_supplied_evidence():
	evidence = {"items": [{"id": "scenario_event:1"}, {"id": "metadata:Sales Invoice"}]}
	output = {
		"answer": "The invoice records a receivable.",
		"claims": [
			{
				"kind": "erpnext_fact",
				"text": "Sales invoices can be submitted.",
				"evidence_ids": ["metadata:Sales Invoice"],
			}
		],
		"proposed_corrections": [],
	}
	assert _parse_output(_response(output), evidence) == output


def test_tutor_rejects_invented_citations():
	evidence = {"items": [{"id": "scenario_event:1"}]}
	output = {
		"answer": "Invented answer",
		"claims": [
			{
				"kind": "scenario_fact",
				"text": "A record exists.",
				"evidence_ids": ["document:Sales Invoice:INVENTED"],
			}
		],
		"proposed_corrections": [],
	}
	with pytest.raises(AIExecutionError, match="not supplied"):
		_parse_output(_response(output), evidence)
