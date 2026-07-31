# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Site tests for adapter discovery and encrypted provider configuration."""

import pytest

pytestmark = pytest.mark.frappe_site


def test_openai_adapter_is_discoverable(frappe_site):
	from frappe_scenario.ai.registry import discover_ai_adapters

	adapter = discover_ai_adapters().get("openai")
	assert adapter.id == "openai"
	assert adapter.describe()["title"] == "OpenAI"


def test_provider_credential_uses_password_storage_and_is_never_disclosed(
	frappe_site, rollback
):
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
