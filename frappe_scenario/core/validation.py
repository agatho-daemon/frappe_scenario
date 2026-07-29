# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Validation primitives.

Severity is deliberately three-valued so that "unusual but possible" business
shapes do not fail a run:

``error``    structurally or financially invalid; the run is not acceptable
``warning``  unusual but possible; reported, does not fail the run
``info``     a generated characteristic or a recorded assumption
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Severity = Literal["error", "warning", "info"]

SEVERITY_ORDER: dict[str, int] = {"info": 0, "warning": 1, "error": 2}


@dataclass
class ValidationIssue:
	rule: str
	severity: Severity
	message: str
	provider: str | None = None
	capability: str | None = None
	doctype: str | None = None
	record: str | None = None
	remediation: str | None = None
	observed: Any = None
	expected: Any = None

	def as_dict(self) -> dict[str, Any]:
		return {
			"rule": self.rule,
			"severity": self.severity,
			"message": self.message,
			"provider": self.provider,
			"capability": self.capability,
			"doctype": self.doctype,
			"record": self.record,
			"remediation": self.remediation,
			"observed": self.observed,
			"expected": self.expected,
		}


@dataclass
class ValidationResult:
	issues: list[ValidationIssue] = field(default_factory=list)

	def add(self, issue: ValidationIssue) -> None:
		self.issues.append(issue)

	def error(self, rule: str, message: str, **kwargs: Any) -> None:
		self.add(ValidationIssue(rule=rule, severity="error", message=message, **kwargs))

	def warning(self, rule: str, message: str, **kwargs: Any) -> None:
		self.add(ValidationIssue(rule=rule, severity="warning", message=message, **kwargs))

	def info(self, rule: str, message: str, **kwargs: Any) -> None:
		self.add(ValidationIssue(rule=rule, severity="info", message=message, **kwargs))

	def extend(self, other: ValidationResult) -> None:
		self.issues.extend(other.issues)

	@property
	def errors(self) -> list[ValidationIssue]:
		return [issue for issue in self.issues if issue.severity == "error"]

	@property
	def warnings(self) -> list[ValidationIssue]:
		return [issue for issue in self.issues if issue.severity == "warning"]

	@property
	def passed(self) -> bool:
		return not self.errors

	def counts(self) -> dict[str, int]:
		counts = {"error": 0, "warning": 0, "info": 0}
		for issue in self.issues:
			counts[issue.severity] += 1
		return counts

	def filtered(self, skip_rules: set[str]) -> ValidationResult:
		"""Drop issues whose rule is explicitly skipped by the specification."""
		if not skip_rules:
			return self
		return ValidationResult(issues=[issue for issue in self.issues if issue.rule not in skip_rules])

	def as_dict(self) -> dict[str, Any]:
		return {
			"passed": self.passed,
			"counts": self.counts(),
			"issues": [issue.as_dict() for issue in self.issues],
		}
