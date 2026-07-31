# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""AI configuration parsing and secret-boundary enforcement."""

from __future__ import annotations

import json
import re
from typing import Any

_SECRET_KEY = re.compile(r"(^|_)(api_?key|token|password|secret|authorization|credential)($|_)", re.I)


def parse_public_configuration(value: str | dict[str, Any] | None) -> dict[str, Any]:
	if not value:
		return {}
	parsed = json.loads(value) if isinstance(value, str) else value
	if not isinstance(parsed, dict):
		raise ValueError("AI provider configuration must be a JSON object.")
	_reject_secrets(parsed)
	return parsed


def _reject_secrets(value: Any, path: str = "configuration") -> None:
	if isinstance(value, dict):
		for key, child in value.items():
			if _SECRET_KEY.search(str(key)):
				raise ValueError(f"Secrets are not allowed in public configuration ({path}.{key}).")
			_reject_secrets(child, f"{path}.{key}")
	elif isinstance(value, list):
		for index, child in enumerate(value):
			_reject_secrets(child, f"{path}[{index}]")
