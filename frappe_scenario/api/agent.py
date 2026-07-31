# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""External-agent endpoints.

These remain the model-independent route: an external agent asks for the
compilation context, compiles elsewhere, and submits data. Built-in adapters do
not weaken this boundary. Every submitted specification remains untrusted and
cannot generate anything until a person approves the draft.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _

from frappe_scenario.api.capabilities import capability_catalog
from frappe_scenario.core.specification import (
	SCHEMA_VERSION,
	load_specification,
	resolve_specification,
)

ROLE = "System Manager"

DRAFT_DOCTYPE = "Scenario AI Draft"

#: Bumped whenever the compilation contract changes in a way an agent must notice.
PROMPT_VERSION = "1"

INSTRUCTIONS = (
	"Compile the brief into a scenario specification that validates against the supplied JSON "
	"schema. Use only the archetypes, country packs, scales, and provider options listed in the "
	"catalogue. Do not invent capabilities. State every value you inferred rather than were told, "
	"and leave anything you cannot justify unset so the platform applies its own defaults."
)


@frappe.whitelist()
def compile_brief(brief: str, constraints: str | dict[str, Any] | None = None) -> dict[str, Any]:
	"""Return the context an external agent needs to compile a brief.

	This never starts generation and never calls a model. It hands back the
	schema and catalogue so the compilation happens outside this app.
	"""
	frappe.only_for(ROLE)
	if not (brief or "").strip():
		frappe.throw(_("A brief is required."))

	catalog = capability_catalog()
	return {
		"prompt_version": PROMPT_VERSION,
		"schema_version": SCHEMA_VERSION,
		"instructions": INSTRUCTIONS,
		"brief": brief,
		"constraints": frappe.parse_json(constraints)
		if isinstance(constraints, str)
		else (constraints or {}),
		"catalog": catalog,
		"catalog_hash": catalog["catalog_hash"],
	}


@frappe.whitelist()
def submit_draft(
	brief: str,
	compiled_specification: str | dict[str, Any],
	title: str | None = None,
	constraints: str | dict[str, Any] | None = None,
	ai_provider: str | None = None,
	ai_model: str | None = None,
	prompt_version: str | None = None,
	catalog_hash: str | None = None,
	draft: str | None = None,
) -> dict[str, Any]:
	"""Store an agent-compiled specification for human review.

	The specification is treated as data: it is parsed and schema-validated, and
	any instruction-like text it contains is never executed.
	"""
	frappe.only_for(ROLE)

	specification = load_specification(compiled_specification)
	resolved, assumptions = resolve_specification(specification)

	doc = frappe.get_doc(DRAFT_DOCTYPE, draft) if draft else frappe.new_doc(DRAFT_DOCTYPE)
	doc.title = title or _title_for(resolved)
	doc.brief = brief
	doc.constraints = _encode(constraints)
	doc.compiled_specification = json.dumps(specification, indent="\t", sort_keys=True)
	doc.assumptions = json.dumps(assumptions, indent="\t", default=str)
	doc.ai_provider = ai_provider
	doc.ai_model = ai_model
	doc.prompt_version = prompt_version or PROMPT_VERSION
	doc.catalog_hash = catalog_hash
	doc.approval_status = "Pending Review"
	doc.save(ignore_permissions=False)

	current_hash = capability_catalog()["catalog_hash"]
	return {
		"draft": doc.name,
		"approval_status": doc.approval_status,
		"assumptions": assumptions,
		"catalog_matches_site": (catalog_hash or current_hash) == current_hash,
	}


@frappe.whitelist()
def approve_draft(draft: str) -> dict[str, Any]:
	"""Approve a draft and turn it into a reusable Scenario Definition."""
	frappe.only_for(ROLE)
	doc = frappe.get_doc(DRAFT_DOCTYPE, draft)
	if not doc.compiled_specification:
		frappe.throw(_("This draft has no compiled specification to approve."))

	doc.approval_status = "Approved"
	doc.save()

	definition = frappe.new_doc("Scenario Definition")
	definition.title = doc.title
	definition.description = doc.brief
	definition.source = "AI Draft"
	definition.ai_draft = doc.name
	definition.specification = doc.compiled_specification
	definition.insert()

	return {"draft": doc.name, "definition": definition.name}


def _title_for(resolved: dict[str, Any]) -> str:
	scenario = resolved.get("scenario") or {}
	return f"{scenario.get('archetype')} / {scenario.get('country')} / {scenario.get('scale')}"


def _encode(value: str | dict[str, Any] | None) -> str | None:
	if value is None:
		return None
	parsed = frappe.parse_json(value) if isinstance(value, str) else value
	return json.dumps(parsed, indent="\t", sort_keys=True, default=str)
