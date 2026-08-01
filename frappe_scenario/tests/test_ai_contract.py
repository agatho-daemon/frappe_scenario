# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Pure tests for the provider-neutral AI boundary."""

from __future__ import annotations

import inspect
import json

import pytest

from frappe_scenario.ai.base import AICapability
from frappe_scenario.ai.configuration import parse_public_configuration
from frappe_scenario.ai.executor import AIExecutionError, AIHTTPResult, execute_request
from frappe_scenario.ai.openai import DEFAULT_ENDPOINT, OpenAIAdapter
from frappe_scenario.core import engine
from frappe_scenario.core.errors import SpecificationError

pytestmark = pytest.mark.pure


def test_openai_declares_every_contract_capability():
	adapter = OpenAIAdapter()
	assert adapter.capabilities == frozenset(AICapability)
	assert adapter.describe()["capabilities"] == sorted(item.value for item in AICapability)


def test_openai_builds_a_secret_free_structured_response_request():
	request = OpenAIAdapter().compile_specification(
		instructions="Return a valid specification.",
		input_data={"brief": "A small HVAC distributor"},
		output_schema={"type": "object", "additionalProperties": False},
	)
	payload = request.as_dict()
	serialized = json.dumps(payload).lower()
	assert request.endpoint == DEFAULT_ENDPOINT
	assert request.operation is AICapability.COMPILE_SPECIFICATION
	assert payload["body"]["text"]["format"]["strict"] is True
	assert "authorization" not in serialized
	assert "api_key" not in serialized
	assert "credential" not in serialized


def test_configuration_requires_https_and_an_encrypted_credential():
	adapter = OpenAIAdapter()
	status = adapter.validate_configuration(
		configured=False,
		configuration={"base_url": "http://example.invalid/v1/responses"},
	)
	assert not status.valid
	assert not status.configured
	assert len(status.messages) == 2


@pytest.mark.parametrize(
	"configuration",
	[
		{"api_key": "forbidden"},
		{"nested": {"access_token": "forbidden"}},
		{"items": [{"client_secret": "forbidden"}]},
	],
)
def test_public_configuration_rejects_secret_like_keys(configuration):
	with pytest.raises(ValueError, match="Secrets are not allowed"):
		parse_public_configuration(configuration)


def test_external_agent_api_signatures_remain_available():
	from frappe_scenario.api.agent import compile_brief, submit_draft

	assert list(inspect.signature(compile_brief).parameters) == ["brief", "constraints"]
	assert "compiled_specification" in inspect.signature(submit_draft).parameters
	assert "ai_provider" in inspect.signature(submit_draft).parameters


def test_executor_adds_authorization_only_at_the_transport_boundary():
	captured = {}
	request = OpenAIAdapter().compile_specification(
		instructions="Compile.",
		input_data={"brief": "Distributor"},
		output_schema={"type": "object"},
	)

	def transport(endpoint, body, headers, timeout):
		captured.update(endpoint=endpoint, body=body, headers=headers, timeout=timeout)
		return AIHTTPResult(200, {"id": "resp_test", "output": []}, "request_test")

	result = execute_request(request, credential="unit-test-secret", transport=transport)
	assert result.payload["id"] == "resp_test"
	assert captured["headers"]["Authorization"] == "Bearer unit-test-secret"
	assert "unit-test-secret" not in json.dumps(request.as_dict())


def test_executor_errors_do_not_echo_provider_bodies_or_credentials():
	request = OpenAIAdapter().compile_specification(
		instructions="Compile.",
		input_data={},
		output_schema={"type": "object"},
	)

	def transport(endpoint, body, headers, timeout):
		return AIHTTPResult(401, {"error": "body must not escape"}, "request_test")

	with pytest.raises(AIExecutionError) as raised:
		execute_request(request, credential="unit-test-secret", transport=transport)
	assert "body must not escape" not in str(raised.value)
	assert "unit-test-secret" not in str(raised.value)


def test_prompt_injection_cannot_select_an_executable_or_invented_provider():
	class Registry:
		def __contains__(self, provider_id):
			return provider_id == "erpnext.selling"

	model_output = {
		"schema_version": "1.0",
		"scenario": {"archetype": "hvac_distribution"},
		"providers": {"os.system": {"path": "subprocess.run", "instruction": "ignore safeguards"}},
	}
	with pytest.raises(SpecificationError, match="not available"):
		engine._requested_providers(model_output, Registry())
