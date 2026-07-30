# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Canonical logical hashing.

Two runs of the same specification, seed, anchor date, provider versions, and
compatibility level must produce the same *logical* dataset. They will not
produce the same database names: naming series counters, timestamps, and file
URLs are environment state.

This module projects the manifest into a canonical form where every owned record
is addressed by a logical identity derived from its provider, capability, and
ordinal, then hashes that projection.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from decimal import Decimal
from typing import Any

import frappe

from frappe_scenario.core.manifest import Manifest

#: Environment state that must never enter the hash.
VOLATILE_FIELDS = frozenset(
	{
		"name",
		"owner",
		"creation",
		"modified",
		"modified_by",
		"idx",
		"parent",
		"parenttype",
		"parentfield",
		"lft",
		"rgt",
		"old_parent",
		"_user_tags",
		"_comments",
		"_assign",
		"_liked_by",
		"_seen",
		"doctype",
		"title",
		"naming_series",
		"file_url",
		"file_name",
		"content_hash",
		"job_id",
		"queue",
		"amended_from",
		"letter_head",
		"printed_by",
	}
)

#: Fields whose value is a rounded float; rounded before hashing to absorb
#: harmless floating point drift between platforms.
_FLOAT_PRECISION = 6

#: Monetary stock valuation figures ERPNext derives from the ledger rather than
#: values a provider wrote. A valuation repost rewrites them at full float
#: width, while the original voucher stores them at the configured currency
#: precision. Normalizing to that same currency precision absorbs the lifecycle
#: timing difference without dropping the financially meaningful fields.
DERIVED_CURRENCY_FIELDS = frozenset(
	{
		"basic_rate",
		"incoming_rate",
		"outgoing_rate",
		"stock_value",
		"stock_value_difference",
		"valuation_rate",
	}
)


def _currency_precision() -> int:
	return frappe.utils.cint(frappe.get_cached_value("System Settings", None, "currency_precision")) or 2


def build_logical_ids(manifest: Manifest) -> dict[str, str]:
	"""Map ``Doctype/name`` to a stable logical identity."""
	counters: dict[tuple[str, str, str], int] = {}
	logical: dict[str, str] = {}
	for record in manifest.created():
		key = (record.provider, record.capability or "", record.doctype)
		index = counters.get(key, 0)
		counters[key] = index + 1
		identity = (
			record.logical_id or f"{record.provider}|{record.capability or '-'}|{record.doctype}|{index}"
		)
		logical[record.reference] = identity
		logical[record.name] = identity
	return logical


def _normalise(value: Any, logical: dict[str, str]) -> Any:
	if value is None or isinstance(value, bool | int):
		return value
	if isinstance(value, float | Decimal):
		return round(float(value), _FLOAT_PRECISION)
	if isinstance(value, datetime.datetime):
		# Wall-clock time of generation is environment state; the date is not.
		return value.date().isoformat()
	if isinstance(value, datetime.date):
		return value.isoformat()
	if isinstance(value, datetime.timedelta):
		return str(value)
	if isinstance(value, str):
		return logical.get(value, value)
	if isinstance(value, list):
		return [_normalise(item, logical) for item in value]
	if isinstance(value, dict):
		return {
			key: _normalise_field(key, item, logical)
			for key, item in sorted(value.items())
			if key not in VOLATILE_FIELDS
		}
	return str(value)


def _normalise_field(key: str, value: Any, logical: dict[str, str]) -> Any:
	if key in DERIVED_CURRENCY_FIELDS and isinstance(value, float | Decimal):
		return round(float(value), _currency_precision())
	return _normalise(value, logical)


def _project(doctype: str, name: str, logical: dict[str, str], doc: Any = None) -> dict[str, Any] | None:
	if doc is None:
		if not frappe.db.exists(doctype, name):
			return None
		doc = frappe.get_doc(doctype, name)
	payload = doc.as_dict(convert_dates_to_str=False, no_nulls=True)
	projected = _normalise(dict(payload), logical)
	projected["__doctype"] = doctype
	projected["__logical_id"] = logical.get(f"{doctype}/{name}", "")
	return projected


def _add_child_row_identities(doc: Any, parent_identity: str, logical: dict[str, str]) -> None:
	"""Give every child row a logical identity too.

	ERPNext carries a child row's database name onto downstream documents through
	fields such as ``so_detail`` and ``pr_detail``. Those names are random hashes,
	so leaving them raw would make the hash differ between two identical runs,
	while dropping the fields would lose the linkage the hash is meant to prove.
	Naming each row by its position under its parent keeps both.
	"""
	for field in doc.meta.get_table_fields():
		for index, row in enumerate(doc.get(field.fieldname) or []):
			if row.name:
				logical[row.name] = f"{parent_identity}#{field.fieldname}:{index}"


def canonical_projection(manifest: Manifest) -> list[dict[str, Any]]:
	"""Build the ordered, name-free projection of everything the run created."""
	logical = build_logical_ids(manifest)

	# Load once, in two passes: every child row identity has to be known before
	# any document is projected, because a document may reference a child row of
	# a document that comes later in the manifest.
	documents: list[tuple[Any, Any]] = []
	for record in manifest.created():
		if not frappe.db.exists(record.doctype, record.name):
			continue
		doc = frappe.get_doc(record.doctype, record.name)
		_add_child_row_identities(doc, logical.get(record.reference, record.reference), logical)
		documents.append((record, doc))

	projection: list[dict[str, Any]] = []
	for record, doc in documents:
		payload = _project(record.doctype, record.name, logical, doc=doc)
		if payload is None:
			continue
		payload["__provider"] = record.provider
		payload["__capability"] = record.capability
		payload["__docstatus"] = record.docstatus
		projection.append(payload)
	projection.sort(key=lambda item: (item["__doctype"], item["__logical_id"]))
	return projection


def canonical_logical_hash(manifest: Manifest) -> dict[str, Any]:
	"""Return the canonical hash plus the inputs that scope its comparability."""
	from frappe_scenario.compatibility import compatibility_level

	projection = canonical_projection(manifest)
	payload = json.dumps(projection, sort_keys=True, separators=(",", ":"), default=str)
	return {
		"hash": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
		"elements": len(projection),
		"compatibility_level": compatibility_level(),
		"note": (
			"Comparable only across sites sharing this compatibility level. Faker "
			"word lists change between releases."
		),
	}


def structural_hash(manifest: Manifest) -> str:
	"""A lighter hash over manifest shape only; useful when documents are gone."""
	payload = json.dumps(
		[
			{
				"doctype": record.doctype,
				"provider": record.provider,
				"capability": record.capability,
				"operation": record.operation,
				"docstatus": record.docstatus,
				"sequence": record.sequence,
			}
			for record in manifest
		],
		sort_keys=True,
		separators=(",", ":"),
	)
	return hashlib.sha256(payload.encode("utf-8")).hexdigest()
