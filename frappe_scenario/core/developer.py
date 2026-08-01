# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Headless developer-dataset compilation and lifecycle automation."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from frappe_scenario.core.errors import (
	CleanupBlockedError,
	SafetyError,
	ScenarioError,
	SpecificationError,
)
from frappe_scenario.core.specification import load_specification, validate_schema

AUTOMATION_FORMAT = "frappe-scenario-automation-1"

EXIT_SUCCESS = 0
EXIT_SPECIFICATION = 10
EXIT_SAFETY = 20
EXIT_EXECUTION = 30
EXIT_VALIDATION = 40
EXIT_CLEANUP = 50

OPERATIONS = ("plan", "generate", "validate", "export", "cleanup")
PROVIDER_ID = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")


def compile_developer_specification(
	base: str | dict[str, Any],
	*,
	seed: int | None = None,
	scale: str | None = None,
	anchor_date: str | None = None,
	providers: list[str] | tuple[str, ...] | None = None,
	partial_delivery_ratio: float | None = None,
	return_ratio: float | None = None,
	overdue_ratio: float | None = None,
	skip_rules: list[str] | tuple[str, ...] | None = None,
	sets: list[str] | tuple[str, ...] | None = None,
	available_providers: set[str] | None = None,
) -> dict[str, Any]:
	"""Apply explicit CI overrides without mutating the source specification."""
	specification = copy.deepcopy(load_specification(base))
	scenario = specification.setdefault("scenario", {})
	scenario["intent"] = "Developer/Test Dataset"

	for key, value in (("seed", seed), ("scale", scale), ("anchor_date", anchor_date)):
		if value is not None:
			scenario[key] = value

	operations = specification.setdefault("operations", {})
	if partial_delivery_ratio is not None:
		operations["partial_deliveries"] = partial_delivery_ratio
	if return_ratio is not None:
		operations["returns"] = return_ratio
	if overdue_ratio is not None:
		specification.setdefault("accounting", {})["overdue_receivables"] = overdue_ratio

	if providers:
		selected = list(dict.fromkeys(providers))
		invalid = [provider for provider in selected if not PROVIDER_ID.fullmatch(provider)]
		unknown = sorted(set(selected) - available_providers) if available_providers is not None else []
		if invalid or unknown:
			raise SpecificationError(
				"Developer provider selection is invalid.",
				phase="compile_developer",
				details={"invalid": invalid, "unknown": unknown},
			)
		current = specification.get("providers") or {}
		specification["providers"] = {
			provider: copy.deepcopy(current.get(provider) or {}) for provider in selected
		}
		specification["provider_selection"] = selected

	if skip_rules:
		validation = specification.setdefault("validation", {})
		validation["skip_rules"] = sorted(set(validation.get("skip_rules") or []).union(skip_rules))

	for assignment in sets or ():
		path, value = parse_assignment(assignment)
		set_json_pointer(specification, path, value)

	problems = validate_schema(specification)
	if problems:
		raise SpecificationError(
			"Developer specification failed schema validation.",
			phase="compile_developer",
			details={"problems": problems},
		)
	return specification


def parse_assignment(assignment: str) -> tuple[str, Any]:
	"""Parse ``/json/pointer=JSON`` without evaluating code."""
	if "=" not in assignment:
		raise SpecificationError(
			"Developer override must use /json/pointer=JSON.",
			phase="compile_developer",
			details={"assignment": assignment},
		)
	path, encoded = assignment.split("=", 1)
	try:
		value = json.loads(encoded)
	except json.JSONDecodeError as exception:
		raise SpecificationError(
			"Developer override value must be valid JSON.",
			phase="compile_developer",
			details={"assignment": assignment, "error": str(exception)},
		) from exception
	return path, value


def set_json_pointer(document: dict[str, Any], pointer: str, value: Any) -> None:
	"""Set a dictionary-only RFC 6901 pointer, creating missing objects."""
	if not pointer.startswith("/") or pointer == "/":
		raise SpecificationError(
			"Developer override path must be a non-root JSON pointer.",
			phase="compile_developer",
			details={"path": pointer},
		)
	parts = [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]
	cursor: dict[str, Any] = document
	for part in parts[:-1]:
		next_value = cursor.setdefault(part, {})
		if not isinstance(next_value, dict):
			raise SpecificationError(
				"Developer override cannot descend through a non-object value.",
				phase="compile_developer",
				details={"path": pointer, "segment": part},
			)
		cursor = next_value
	cursor[parts[-1]] = value


def automate(
	operation: str,
	target: str | dict[str, Any],
	*,
	allow_non_disposable: bool = False,
) -> tuple[dict[str, Any], int]:
	"""Execute one headless lifecycle operation and return an envelope plus exit code."""
	from frappe_scenario.core import engine

	if operation not in OPERATIONS:
		error = SpecificationError(
			f"Unknown automation operation {operation!r}.",
			phase="automation",
			details={"known": list(OPERATIONS)},
		)
		return failure_envelope(operation, error)

	try:
		if operation == "plan":
			data = engine.plan(target, allow_non_disposable=allow_non_disposable)
		elif operation == "generate":
			planned = engine.plan(target, allow_non_disposable=allow_non_disposable)
			if planned["blocked"]:
				raise SafetyError(
					"Target site is not approved for scenario generation.",
					phase="generate",
					details={"safety": planned["safety"]},
				)
			run_name = engine.create_run(target)
			engine.approve_run(run_name)
			data = engine.execute_run(run_name, allow_non_disposable=allow_non_disposable)
			if data.get("status") != "Completed":
				return envelope(operation, False, data, EXIT_EXECUTION), EXIT_EXECUTION
		elif operation == "validate":
			data = engine.validate_run(str(target))
			if not data.get("passed"):
				return envelope(operation, False, data, EXIT_VALIDATION), EXIT_VALIDATION
		elif operation == "export":
			data = engine.export_run(str(target))
		else:
			data = engine.cleanup_run(str(target), allow_non_disposable=allow_non_disposable)
			if data.get("blockers"):
				return envelope(operation, False, data, EXIT_CLEANUP), EXIT_CLEANUP
		return envelope(operation, True, data, EXIT_SUCCESS), EXIT_SUCCESS
	except ScenarioError as error:
		return failure_envelope(operation, error)


def envelope(operation: str, ok: bool, data: dict[str, Any], exit_code: int) -> dict[str, Any]:
	return {
		"format": AUTOMATION_FORMAT,
		"operation": operation,
		"ok": ok,
		"exit_code": exit_code,
		"data": data,
		"error": None,
	}


def failure_envelope(operation: str, error: ScenarioError) -> tuple[dict[str, Any], int]:
	exit_code = exit_code_for_error(error)
	return {
		"format": AUTOMATION_FORMAT,
		"operation": operation,
		"ok": False,
		"exit_code": exit_code,
		"data": None,
		"error": error.as_dict(),
	}, exit_code


def exit_code_for_error(error: ScenarioError) -> int:
	if isinstance(error, SpecificationError):
		return EXIT_SPECIFICATION
	if isinstance(error, SafetyError):
		return EXIT_SAFETY
	if isinstance(error, CleanupBlockedError) or error.phase == "cleanup":
		return EXIT_CLEANUP
	if error.phase == "validate":
		return EXIT_VALIDATION
	return EXIT_EXECUTION


def write_json(payload: dict[str, Any], output: str | None = None) -> str:
	"""Serialize consistently; file output is useful to CI artifact collectors."""
	encoded = json.dumps(payload, indent="\t", sort_keys=True, default=str) + "\n"
	if output:
		Path(output).write_text(encoded, encoding="utf-8")
	return encoded
