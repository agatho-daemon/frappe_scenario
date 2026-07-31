# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Site tests for adapter discovery and encrypted provider configuration."""

import json

import pytest

pytestmark = pytest.mark.frappe_site


def test_openai_adapter_is_discoverable(frappe_site):
	from frappe_scenario.ai.registry import discover_ai_adapters

	adapter = discover_ai_adapters().get("openai")
	assert adapter.id == "openai"
	assert adapter.describe()["title"] == "OpenAI"


def test_provider_credential_uses_password_storage_and_is_never_disclosed(frappe_site, rollback):
	import frappe

	from frappe_scenario.api.ai import describe_ai_adapters

	doc = frappe.get_doc(
		{
			"doctype": "Scenario AI Provider",
			"provider": "openai",
			"enabled": 1,
			"model": "gpt-5.6-sol",
			"credential": "test-secret-never-return",
			"configuration": '{"base_url": "https://api.openai.com/v1/responses"}',
		}
	).insert()

	assert frappe.get_meta(doc.doctype).get_field("credential").fieldtype == "Password"
	assert doc.get_password("credential") == "test-secret-never-return"
	response = describe_ai_adapters()
	assert response["external_agent"]["available"] is True
	openai = next(item for item in response["adapters"] if item["id"] == "openai")
	assert openai["configuration"] == {"valid": True, "configured": True, "messages": []}
	assert "test-secret-never-return" not in str(response)


def test_ai_brief_compilation_stores_validated_provenance_without_generating(
	frappe_site, rollback, smoke_specification, monkeypatch
):
	import frappe

	from frappe_scenario.ai.compilation import compile_ai_brief
	from frappe_scenario.ai.executor import AIHTTPResult

	frappe.get_doc(
		{
			"doctype": "Scenario AI Provider",
			"provider": "openai",
			"enabled": 1,
			"model": "gpt-5.6-sol",
			"credential": "test-secret-never-return",
		}
	).insert()
	model_output = {
		"compiled_specification": json.dumps(smoke_specification),
		"assumptions": ["The company distributes HVAC equipment."],
		"inferred_values": [
			{"path": "/scenario/country", "value": "Kuwait", "reason": "The brief named Kuwait."}
		],
	}
	captured = {}
	runs_before = frappe.db.count("Scenario Run")

	def transport(endpoint, body, headers, timeout):
		captured.update(headers=headers, body=body)
		return AIHTTPResult(
			200,
			{
				"id": "resp_scenario_test",
				"usage": {"input_tokens": 100, "output_tokens": 50},
				"output": [
					{
						"type": "message",
						"content": [{"type": "output_text", "text": json.dumps(model_output)}],
					}
				],
			},
			"request_scenario_test",
		)

	result = compile_ai_brief(
		"Create a realistic Kuwait HVAC distributor.",
		constraints={"scale": "smoke"},
		transport=transport,
	)
	draft = frappe.get_doc("Scenario AI Draft", result["draft"])
	assert result["approval_status"] == "Pending Review"
	assert result["preview"]["scenario"]["country"] == "Kuwait"
	assert draft.provider_response_id == "resp_scenario_test"
	assert draft.model_output_hash
	assert json.loads(draft.model_output) == model_output
	assert json.loads(draft.inferred_values) == model_output["inferred_values"]
	assert not draft.edited_by_human
	assert captured["headers"]["Authorization"] == "Bearer test-secret-never-return"
	assert "test-secret-never-return" not in json.dumps(captured["body"])
	assert frappe.db.count("Scenario Run") == runs_before

	edited = json.loads(draft.compiled_specification)
	edited["scenario"]["seed"] += 1
	draft.compiled_specification = json.dumps(edited)
	draft.save()
	assert draft.edited_by_human

	monkeypatch.setattr(
		"frappe_scenario.api.agent.capability_catalog",
		lambda: {"catalog_hash": "catalogue-changed-after-compilation"},
	)
	from frappe_scenario.api.agent import approve_draft

	with pytest.raises(frappe.ValidationError, match="capability catalogue changed"):
		approve_draft(draft.name)
	assert not frappe.db.exists("Scenario Definition", {"ai_draft": draft.name})


def test_malformed_ai_output_creates_no_draft(frappe_site, rollback):
	import frappe

	from frappe_scenario.ai.compilation import compile_ai_brief
	from frappe_scenario.ai.executor import AIHTTPResult

	frappe.get_doc(
		{
			"doctype": "Scenario AI Provider",
			"provider": "openai",
			"enabled": 1,
			"credential": "test-secret-never-return",
		}
	).insert()
	drafts_before = frappe.db.count("Scenario AI Draft")

	def malformed_transport(endpoint, body, headers, timeout):
		return AIHTTPResult(
			200,
			{
				"output": [
					{
						"type": "message",
						"content": [{"type": "output_text", "text": '{"assumptions": []}'}],
					}
				]
			},
		)

	with pytest.raises(frappe.ValidationError, match="failed its contract"):
		compile_ai_brief("Create a distributor.", transport=malformed_transport)
	assert frappe.db.count("Scenario AI Draft") == drafts_before
