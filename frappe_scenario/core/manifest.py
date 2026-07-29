# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Ownership manifest.

Every record a provider creates, and every pre-existing value it modifies, is
recorded here. The manifest is the only authority cleanup consults, which is how
the platform guarantees it never touches a record it did not create.

The detailed manifest is stored as a private JSONL File attached to the Scenario
Run rather than as one database row per generated record.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

MANIFEST_VERSION = "1.0"


@dataclass
class ManifestRecord:
	doctype: str
	name: str
	provider: str
	capability: str | None = None
	operation: str = "created"
	docstatus: int = 0
	sequence: int = 0
	dependencies: list[str] = field(default_factory=list)
	original_values: dict[str, Any] | None = None
	logical_id: str | None = None

	def as_dict(self) -> dict[str, Any]:
		payload: dict[str, Any] = {
			"doctype": self.doctype,
			"name": self.name,
			"provider": self.provider,
			"capability": self.capability,
			"operation": self.operation,
			"docstatus": self.docstatus,
			"sequence": self.sequence,
			"dependencies": list(self.dependencies),
		}
		if self.logical_id:
			payload["logical_id"] = self.logical_id
		if self.original_values is not None:
			payload["original_values"] = self.original_values
		return payload

	@classmethod
	def from_dict(cls, payload: dict[str, Any]) -> ManifestRecord:
		return cls(
			doctype=payload["doctype"],
			name=payload["name"],
			provider=payload.get("provider", ""),
			capability=payload.get("capability"),
			operation=payload.get("operation", "created"),
			docstatus=int(payload.get("docstatus") or 0),
			sequence=int(payload.get("sequence") or 0),
			dependencies=list(payload.get("dependencies") or []),
			original_values=payload.get("original_values"),
			logical_id=payload.get("logical_id"),
		)

	@property
	def reference(self) -> str:
		return f"{self.doctype}/{self.name}"


class Manifest:
	"""An append-only, ordered log of scenario-owned records."""

	def __init__(self, records: Iterable[ManifestRecord] | None = None):
		self._records: list[ManifestRecord] = list(records or [])
		self._seen: set[tuple[str, str, str]] = {
			(record.doctype, record.name, record.operation) for record in self._records
		}

	def __len__(self) -> int:
		return len(self._records)

	def __iter__(self) -> Iterator[ManifestRecord]:
		return iter(self._records)

	@property
	def records(self) -> list[ManifestRecord]:
		return list(self._records)

	def append(self, record: ManifestRecord) -> ManifestRecord:
		key = (record.doctype, record.name, record.operation)
		if key in self._seen:
			# Re-recording the same document (for example after submit) refreshes
			# docstatus rather than duplicating the entry.
			for existing in self._records:
				if (existing.doctype, existing.name, existing.operation) == key:
					existing.docstatus = record.docstatus
					existing.dependencies = list(
						dict.fromkeys([*existing.dependencies, *record.dependencies])
					)
					return existing
		record.sequence = len(self._records)
		self._records.append(record)
		self._seen.add(key)
		return record

	def created(self) -> list[ManifestRecord]:
		return [record for record in self._records if record.operation == "created"]

	def modified(self) -> list[ManifestRecord]:
		return [record for record in self._records if record.operation == "modified"]

	def for_capability(self, capability: str) -> list[ManifestRecord]:
		return [record for record in self._records if record.capability == capability]

	def for_provider(self, provider_id: str) -> list[ManifestRecord]:
		return [record for record in self._records if record.provider == provider_id]

	def counts_by_doctype(self) -> dict[str, int]:
		counts: dict[str, int] = {}
		for record in self.created():
			counts[record.doctype] = counts.get(record.doctype, 0) + 1
		return dict(sorted(counts.items()))

	def counts_by_provider(self) -> dict[str, int]:
		counts: dict[str, int] = {}
		for record in self.created():
			counts[record.provider] = counts.get(record.provider, 0) + 1
		return dict(sorted(counts.items()))

	def truncate_after(self, sequence: int) -> list[ManifestRecord]:
		"""Drop records added after ``sequence``; used when a provider is rolled back."""
		dropped = [record for record in self._records if record.sequence > sequence]
		self._records = [record for record in self._records if record.sequence <= sequence]
		self._seen = {(record.doctype, record.name, record.operation) for record in self._records}
		return dropped

	def to_jsonl(self) -> str:
		lines = [json.dumps({"manifest_version": MANIFEST_VERSION}, sort_keys=True)]
		lines.extend(json.dumps(record.as_dict(), sort_keys=True, default=str) for record in self._records)
		return "\n".join(lines) + "\n"

	@classmethod
	def from_jsonl(cls, payload: str) -> Manifest:
		records: list[ManifestRecord] = []
		for line in payload.splitlines():
			line = line.strip()
			if not line:
				continue
			data = json.loads(line)
			if "manifest_version" in data and "doctype" not in data:
				continue
			records.append(ManifestRecord.from_dict(data))
		records.sort(key=lambda record: record.sequence)
		return cls(records)
