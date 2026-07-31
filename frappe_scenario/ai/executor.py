# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Audited HTTP execution boundary for provider adapter requests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import requests

from frappe_scenario.ai.base import AIRequest


class AIExecutionError(RuntimeError):
	"""A safe provider failure that never contains a credential or response body."""


@dataclass(frozen=True)
class AIHTTPResult:
	status_code: int
	payload: dict[str, Any]
	request_id: str | None = None


AITransport = Callable[[str, dict[str, Any], dict[str, str], float], AIHTTPResult]


def execute_request(
	request: AIRequest,
	*,
	credential: str,
	timeout: float = 120,
	transport: AITransport | None = None,
) -> AIHTTPResult:
	"""Execute a prepared request while keeping authorization out of the adapter."""
	if not credential:
		raise AIExecutionError("The AI provider credential is not configured.")
	headers = {**request.headers, "Authorization": f"Bearer {credential}"}
	try:
		result = (transport or _post)(request.endpoint, request.body, headers, timeout)
	except AIExecutionError:
		raise
	except Exception as exception:
		raise AIExecutionError(
			f"The {request.provider} request could not be completed ({type(exception).__name__})."
		) from exception
	if not 200 <= result.status_code < 300:
		raise AIExecutionError(
			f"The {request.provider} request failed with HTTP {result.status_code}"
			+ (f" (request {result.request_id})" if result.request_id else "")
			+ "."
		)
	return result


def _post(
	endpoint: str,
	body: dict[str, Any],
	headers: dict[str, str],
	timeout: float,
) -> AIHTTPResult:
	response = requests.post(
		endpoint,
		json=body,
		headers=headers,
		timeout=timeout,
		allow_redirects=False,
	)
	request_id = response.headers.get("x-request-id")
	try:
		payload = response.json()
	except ValueError as exception:
		raise AIExecutionError(
			"The AI provider returned a response that was not valid JSON"
			+ (f" (request {request_id})" if request_id else "")
			+ "."
		) from exception
	if not isinstance(payload, dict):
		raise AIExecutionError("The AI provider returned an unexpected JSON value.")
	return AIHTTPResult(response.status_code, payload, request_id)
