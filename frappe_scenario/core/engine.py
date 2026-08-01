# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""The scenario engine.

This is the single service layer. The Bench CLI, the agent API, and any future
Desk UI all call these functions; none of them re-implement orchestration.

Execution model:

* one database savepoint per provider;
* a provider failure rolls that provider back and leaves the run error report;
* a checkpoint (commit + manifest flush + capability snapshot) is taken after
  each provider, so ``resume`` restarts at a provider boundary and never in the
  middle of an indivisible business transaction.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import time
import traceback
from typing import Any

import frappe
from frappe.utils import now_datetime

from frappe_scenario.compatibility import compatibility_level, installed_app_versions
from frappe_scenario.core.canonical import canonical_logical_hash, structural_hash
from frappe_scenario.core.context import ScenarioContext
from frappe_scenario.core.dependency_graph import resolve_graph
from frappe_scenario.core.discovery import discover_providers
from frappe_scenario.core.errors import ScenarioError, SpecificationError
from frappe_scenario.core.manifest import Manifest
from frappe_scenario.core.provider import ScenarioProvider
from frappe_scenario.core.safety import assert_safe_to_generate, site_safety_report
from frappe_scenario.core.specification import (
	load_specification,
	resolve_specification,
	specification_hash,
)
from frappe_scenario.core.validation import ValidationResult

RUN_DOCTYPE = "Scenario Run"
VALIDATION_DOCTYPE = "Scenario Validation Result"
MANIFEST_FILENAME = "manifest.jsonl"


def _manifest_filename(run_name: str) -> str:
	"""Use a physical filename unique to one run; Frappe deduplicates files."""
	return f"{run_name}-{MANIFEST_FILENAME}"


STATUS_DRAFT = "Draft"
STATUS_QUEUED = "Queued"
STATUS_RUNNING = "Running"
STATUS_CANCELLATION_REQUESTED = "Cancellation Requested"
STATUS_CANCELLED = "Cancelled"
STATUS_COMPLETED = "Completed"
STATUS_FAILED = "Failed"
STATUS_CLEANED = "Cleaned Up"


# ---------------------------------------------------------------------------
# planning
# ---------------------------------------------------------------------------
def plan(specification: str | dict[str, Any], *, allow_non_disposable: bool = False) -> dict[str, Any]:
	"""Produce a read-only execution plan. Writes nothing."""
	raw = load_specification(specification)
	resolved, assumptions = resolve_specification(raw)

	registry = discover_providers()
	requested = _requested_providers(resolved, registry)
	graph = resolve_graph(registry, requested)

	context = ScenarioContext(run_id="plan", specification=resolved, dry_run=True)

	provider_plans: list[dict[str, Any]] = []
	unsupported: list[str] = []
	settings_changed: list[str] = []
	cleanup_notes: list[str] = []
	total = 0

	for provider in graph.order:
		context.current_provider = provider.id
		provider_plan = provider.plan(context)
		payload = provider_plan.as_dict()
		payload["version"] = provider.version
		payload["role"] = provider.role
		provider_plans.append(payload)
		total += provider_plan.estimated_records
		unsupported.extend(provider_plan.unsupported)
		settings_changed.extend(provider_plan.settings_changed)
		cleanup_notes.extend(provider_plan.cleanup_notes)
		assumptions.extend(
			{"path": f"/providers/{provider.id}", "value": note, "reason": "provider assumption"}
			for note in provider_plan.assumptions
		)

	safety = site_safety_report()
	blocked = not safety["generation_allowed"] and not allow_non_disposable
	from frappe_scenario.core.capacity import estimate_resources

	resources = estimate_resources(resolved, total)

	return {
		"schema_version": resolved["schema_version"],
		"specification": resolved,
		"specification_hash": specification_hash(resolved),
		"assumptions": assumptions,
		"providers": provider_plans,
		"execution_order": [provider.id for provider in graph.order],
		"dependency_graph": graph.as_dict(),
		"provider_versions": {provider.id: provider.version for provider in graph.order},
		"required_apps": sorted({app for provider in graph.order for app in provider.requires_apps}),
		"required_capabilities": sorted(
			{capability for provider in graph.order for capability in provider.requires_capabilities}
		),
		"estimated_records": total,
		"resource_estimate": resources,
		"confirmation_required": resources["confirmation_required"],
		"warnings": resources["warnings"],
		"unsupported": unsupported,
		"settings_changed": settings_changed,
		"cleanup_notes": cleanup_notes,
		"compatibility": compatibility_level(),
		"installed_apps": installed_app_versions(),
		"safety": safety,
		"blocked": blocked,
		"validation_rules": _expected_validation_rules(graph.order),
	}


def _requested_providers(resolved: dict[str, Any], registry: Any) -> set[str] | None:
	"""Providers explicitly named in the specification, or all available ones."""
	explicit = list(resolved.get("provider_selection") or (resolved.get("providers") or {}).keys())
	if not explicit:
		return None
	unknown = sorted(provider_id for provider_id in explicit if provider_id not in registry)
	if unknown:
		raise SpecificationError(
			"Specification requests providers that are not available.",
			phase="plan",
			details={"unknown_providers": unknown},
		)
	return set(explicit)


def _expected_validation_rules(providers: list[ScenarioProvider]) -> list[str]:
	rules: set[str] = set()
	for provider in providers:
		for capability in provider.capabilities:
			rules.update(capability.validation_rules)
	return sorted(rules)


# ---------------------------------------------------------------------------
# run lifecycle
# ---------------------------------------------------------------------------
def create_run(
	specification: str | dict[str, Any],
	*,
	title: str | None = None,
	definition: str | None = None,
	approved: bool = False,
) -> str:
	"""Persist an immutable run snapshot. Does not generate anything."""
	execution_plan = plan(specification)
	resolved = execution_plan["specification"]

	run = frappe.new_doc(RUN_DOCTYPE)
	run.title = title or _default_title(resolved)
	run.scenario_definition = definition
	run.status = STATUS_DRAFT
	run.specification = json.dumps(resolved, indent="\t", sort_keys=True)
	run.specification_hash = execution_plan["specification_hash"]
	run.seed = resolved["scenario"]["seed"]
	run.anchor_date = resolved["scenario"]["anchor_date"]
	run.scale = resolved["scenario"]["scale"]
	run.country = resolved["scenario"].get("country")
	run.currency = resolved["scenario"].get("currency")
	run.archetype = resolved["scenario"]["archetype"]
	run.plan_json = json.dumps(execution_plan, indent="\t", default=str)
	run.assumptions = json.dumps(execution_plan["assumptions"], indent="\t", default=str)
	run.compatibility = json.dumps(
		{
			"compatibility": execution_plan["compatibility"],
			"installed_apps": execution_plan["installed_apps"],
			"provider_versions": execution_plan["provider_versions"],
		},
		indent="\t",
		default=str,
	)
	run.estimated_records = execution_plan["estimated_records"]
	run.approved = 1 if approved else 0
	if approved:
		run.approved_by = frappe.session.user

	for provider_id in execution_plan["execution_order"]:
		run.append(
			"steps",
			{
				"provider": provider_id,
				"provider_version": execution_plan["provider_versions"][provider_id],
				"status": "Pending",
			},
		)

	run.insert(ignore_permissions=True)
	frappe.db.commit()
	return run.name


def _default_title(resolved: dict[str, Any]) -> str:
	scenario = resolved["scenario"]
	return f"{scenario['archetype']} / {scenario.get('country') or 'generic'} / {scenario['scale']}"


def approve_run(run_name: str) -> dict[str, Any]:
	run = frappe.get_doc(RUN_DOCTYPE, run_name)
	if run.status not in (STATUS_DRAFT,):
		raise ScenarioError(
			f"Run {run_name} cannot be approved from status {run.status!r}.",
			phase="approve",
		)
	run.db_set("approved", 1, update_modified=False)
	run.db_set("approved_by", frappe.session.user, update_modified=False)
	frappe.db.commit()
	return {"run_id": run_name, "approved": True, "approved_by": frappe.session.user}


def enqueue_run(run_name: str, *, allow_non_disposable: bool = False) -> dict[str, Any]:
	"""Queue background generation on the long queue."""
	run = frappe.get_doc(RUN_DOCTYPE, run_name)
	_assert_runnable(run, allow_non_disposable=allow_non_disposable)

	run.db_set("status", STATUS_QUEUED, update_modified=False)
	frappe.db.commit()

	job = frappe.enqueue(
		"frappe_scenario.core.engine.execute_run",
		queue="long",
		timeout=8 * 60 * 60,
		run_name=run_name,
		allow_non_disposable=allow_non_disposable,
		job_name=f"frappe_scenario::{run_name}",
	)
	return {"run_id": run_name, "status": STATUS_QUEUED, "job_id": getattr(job, "id", None)}


def _assert_runnable(run: Any, *, allow_non_disposable: bool, accept_queued: bool = False) -> None:
	assert_safe_to_generate(allow_non_disposable=allow_non_disposable)
	if not run.approved:
		raise ScenarioError(
			f"Run {run.name} has not been approved. Generation requires explicit approval.",
			phase="run",
			details={"run_id": run.name},
		)
	active = {STATUS_RUNNING, STATUS_CANCELLATION_REQUESTED}
	if not accept_queued:
		active.add(STATUS_QUEUED)
	if run.status in active:
		raise ScenarioError(
			f"Run {run.name} is already {run.status.lower()}.",
			phase="run",
			details={"run_id": run.name, "status": run.status},
		)
	if run.status == STATUS_CLEANED:
		raise ScenarioError(
			f"Run {run.name} has been cleaned up and cannot be re-executed.",
			phase="run",
			details={"run_id": run.name},
		)
	if run.status in (STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED):
		raise ScenarioError(
			f"Run {run.name} cannot start from status {run.status!r}; use resume or retry where applicable.",
			phase="run",
			details={"run_id": run.name, "status": run.status},
		)

	stored_hash = specification_hash(json.loads(run.specification))
	if stored_hash != run.specification_hash:
		raise SpecificationError(
			"The stored specification no longer matches its approved hash.",
			phase="run",
			details={"run_id": run.name, "expected": run.specification_hash, "found": stored_hash},
		)


def execute_run(
	run_name: str,
	*,
	allow_non_disposable: bool = False,
	resume: bool = False,
) -> dict[str, Any]:
	"""Execute (or resume) a run. Safe to call synchronously or from a worker."""
	run = frappe.get_doc(RUN_DOCTYPE, run_name)
	if not resume:
		if run.status == STATUS_CANCELLED:
			return {"run_id": run.name, "status": STATUS_CANCELLED, "record_count": run.record_count or 0}
		_assert_runnable(
			run,
			allow_non_disposable=allow_non_disposable,
			accept_queued=True,
		)
	else:
		assert_safe_to_generate(allow_non_disposable=allow_non_disposable)

	resolved = json.loads(run.specification)
	registry = discover_providers()
	graph = resolve_graph(registry, _requested_providers(resolved, registry))

	manifest = load_manifest(run) if resume else Manifest()
	context = ScenarioContext(run_id=run.name, specification=resolved, manifest=manifest)
	context.set_progress_callback(lambda payload: _publish_progress(run.name, payload))

	if resume:
		context.restore_capabilities(json.loads(run.published_capabilities or "{}"), publisher="resume")

	completed = {step.provider for step in run.steps if step.status == "Completed"} if resume else set()

	if resume:
		run.db_set("cancellation_requested", 0, update_modified=False)
	run.db_set("status", STATUS_RUNNING, update_modified=False)
	run.db_set("started_at", now_datetime(), update_modified=False)
	run.db_set("error", None, update_modified=False)
	frappe.db.commit()

	failure: dict[str, Any] | None = None
	cancelled = False

	for index, provider in enumerate(graph.order):
		if provider.id in completed:
			continue
		if _cancellation_requested(run.name):
			cancelled = True
			break

		step = _step_for(run, provider.id)
		savepoint = f"scn_{index}"
		checkpoint = len(manifest) - 1
		capabilities_before = _serialisable(context.published_capabilities)
		input_fingerprint = phase_input_fingerprint(
			provider_id=provider.id,
			provider_version=provider.version,
			specification_hash_value=run.specification_hash,
			capabilities=capabilities_before,
		)
		started = time.perf_counter()

		_update_step(
			run,
			step,
			status="Running",
			started_at=now_datetime(),
			attempts=int(step.attempts or 0) + 1,
			manifest_start_sequence=checkpoint,
			input_fingerprint=input_fingerprint,
		)
		frappe.db.commit()

		frappe.db.savepoint(savepoint)
		context.current_provider = provider.id
		context.current_capability = None

		try:
			result = provider.generate(context)
		except Exception as exception:
			frappe.db.rollback(save_point=savepoint)
			manifest.truncate_after(checkpoint)
			failure = _describe_failure(provider, exception)
			_update_step(
				run,
				step,
				status="Failed",
				finished_at=now_datetime(),
				duration_ms=int((time.perf_counter() - started) * 1000),
				error=json.dumps(failure, indent="\t", default=str),
			)
			break

		capabilities_after = _serialisable(context.published_capabilities)
		phase_records = manifest.records[checkpoint + 1 :]
		_update_step(
			run,
			step,
			status="Completed",
			finished_at=now_datetime(),
			duration_ms=int((time.perf_counter() - started) * 1000),
			created_count=sum(
				1 for record in manifest.records[checkpoint + 1 :] if record.operation == "created"
			),
			modified_count=sum(
				1 for record in manifest.records[checkpoint + 1 :] if record.operation == "modified"
			),
			checkpoint_sequence=len(manifest) - 1,
			output_fingerprint=phase_output_fingerprint(
				provider_id=provider.id,
				result={"summary": result.summary, "warnings": result.warnings},
				capabilities=capabilities_after,
				records=[record.as_dict() for record in phase_records],
			),
			capability_snapshot=json.dumps(capabilities_after, indent="\t", default=str),
			warnings=json.dumps(result.warnings, default=str) if result.warnings else None,
			summary=json.dumps(result.summary, indent="\t", default=str) if result.summary else None,
		)

		# Checkpoint: everything up to here is durable and recorded as owned.
		_persist_manifest(run, manifest)
		run.db_set(
			"published_capabilities",
			json.dumps(_serialisable(context.published_capabilities), indent="\t", default=str),
			update_modified=False,
		)
		frappe.db.commit()
		if _cancellation_requested(run.name):
			cancelled = True
			break

	if not failure and not cancelled:
		# Backdated documents leave ERPNext work queued for a background worker.
		# Settle it here so a completed run is consistent on its own terms.
		try:
			deferred = context.adapter.flush_deferred_work()
			if deferred.get("processed"):
				context.warning(
					f"Ran {len(deferred['processed'])} deferred item valuation reposts that "
					"ERPNext had queued for a background worker."
				)
		except Exception as exception:
			failure = _describe_failure(graph.order[-1], exception)
		frappe.db.commit()

	manifest_summary = {
		"total": len(manifest),
		"created": len(manifest.created()),
		"modified": len(manifest.modified()),
		"by_doctype": manifest.counts_by_doctype(),
		"by_provider": manifest.counts_by_provider(),
	}

	_persist_manifest(run, manifest)
	run.db_set("manifest_summary", json.dumps(manifest_summary, indent="\t"), update_modified=False)
	run.db_set("record_count", len(manifest.created()), update_modified=False)
	run.db_set("warnings", json.dumps(context.warnings, indent="\t", default=str), update_modified=False)
	run.db_set("finished_at", now_datetime(), update_modified=False)

	if failure or cancelled:
		status = STATUS_CANCELLED if cancelled else STATUS_FAILED
		run.db_set("status", status, update_modified=False)
		run.db_set("cancellation_requested", 0, update_modified=False)
		run.db_set(
			"error",
			json.dumps(failure, indent="\t", default=str) if failure else None,
			update_modified=False,
		)
		frappe.db.commit()
		return {
			"run_id": run.name,
			"status": status,
			"record_count": len(manifest.created()),
			"error": failure,
			"manifest": manifest_summary,
			"warnings": context.warnings,
		}

	company = context.optional("erpnext.foundation.company")
	if company:
		run.db_set("company", company, update_modified=False)

	canonical = canonical_logical_hash(manifest)
	structural = structural_hash(manifest)
	run.db_set("canonical_hash", canonical["hash"], update_modified=False)
	run.db_set("structural_hash", structural, update_modified=False)
	run.db_set("canonical_details", json.dumps(canonical, indent="\t", default=str), update_modified=False)
	from frappe_scenario.core.outcomes import build_outcome_summary

	outcomes = build_outcome_summary(context)
	run.db_set("outcome_summary", json.dumps(outcomes, indent="\t", default=str), update_modified=False)
	from frappe_scenario.core.narrative import build_scenario_events

	events = build_scenario_events(run, context.published_capabilities)
	run.db_set("status", STATUS_COMPLETED, update_modified=False)
	from frappe_scenario.core.experimentation import ensure_baseline

	ensure_baseline(run.name)
	frappe.db.commit()

	return {
		"run_id": run.name,
		"status": STATUS_COMPLETED,
		"company": company,
		"record_count": len(manifest.created()),
		"manifest": manifest_summary,
		"canonical_hash": canonical["hash"],
		"structural_hash": structural,
		"outcomes": outcomes,
		"event_count": len(events),
		"warnings": context.warnings,
	}


def resume_run(run_name: str, *, allow_non_disposable: bool = False) -> dict[str, Any]:
	run = frappe.get_doc(RUN_DOCTYPE, run_name)
	if run.status not in (STATUS_FAILED, STATUS_CANCELLED):
		raise ScenarioError(
			f"Only failed or cancelled runs can be resumed. Run {run_name} is {run.status!r}.",
			phase="resume",
		)
	return execute_run(run_name, allow_non_disposable=allow_non_disposable, resume=True)


def retry_run(run_name: str, *, allow_non_disposable: bool = False) -> dict[str, Any]:
	"""Retry the failed phase and then resume at the same durable boundary."""
	run = frappe.get_doc(RUN_DOCTYPE, run_name)
	if run.status != STATUS_FAILED:
		raise ScenarioError(
			f"Only failed runs can be retried. Run {run_name} is {run.status!r}.",
			phase="retry",
		)
	return execute_run(run_name, allow_non_disposable=allow_non_disposable, resume=True)


def request_cancellation(run_name: str) -> dict[str, Any]:
	"""Request a cooperative stop; the engine honours it at a provider boundary."""
	run = frappe.get_doc(RUN_DOCTYPE, run_name)
	if run.status not in (STATUS_QUEUED, STATUS_RUNNING, STATUS_CANCELLATION_REQUESTED):
		raise ScenarioError(
			f"Run {run_name} cannot be cancelled from status {run.status!r}.",
			phase="cancel",
		)
	if run.status == STATUS_QUEUED:
		# No phase has started, so cancellation is already at a safe boundary.
		run.db_set("cancellation_requested", 0, update_modified=False)
		run.db_set("status", STATUS_CANCELLED, update_modified=False)
		status = STATUS_CANCELLED
	else:
		run.db_set("cancellation_requested", 1, update_modified=False)
		run.db_set("status", STATUS_CANCELLATION_REQUESTED, update_modified=False)
		status = STATUS_CANCELLATION_REQUESTED
	frappe.db.commit()
	return {"run_id": run.name, "status": status}


def _cancellation_requested(run_name: str) -> bool:
	return bool(frappe.db.get_value(RUN_DOCTYPE, run_name, "cancellation_requested"))


def rollback_last_phase(run_name: str, *, allow_non_disposable: bool = False) -> dict[str, Any]:
	"""Remove the last committed provider phase and leave the run resumable."""
	assert_safe_to_generate(allow_non_disposable=allow_non_disposable)
	run = frappe.get_doc(RUN_DOCTYPE, run_name)
	if run.status not in (STATUS_FAILED, STATUS_CANCELLED):
		raise ScenarioError(
			"Phase rollback is available only for a failed or cancelled run.",
			phase="rollback_phase",
		)
	completed = [step for step in run.steps if step.status == "Completed"]
	if not completed:
		raise ScenarioError("This run has no committed phase to roll back.", phase="rollback_phase")
	step = completed[-1]
	manifest = load_manifest(run)
	start = int(step.manifest_start_sequence if step.manifest_start_sequence is not None else -1)
	end = int(step.checkpoint_sequence if step.checkpoint_sequence is not None else -1)
	records = [record for record in manifest if start < record.sequence <= end]
	provider = discover_providers().get(step.provider)
	context = ScenarioContext(run_id=run.name, specification=json.loads(run.specification), manifest=manifest)
	context.current_provider = provider.id
	result = provider.cleanup(context, records)
	frappe.db.commit()
	if result.blockers:
		return {
			"run_id": run.name,
			"status": STATUS_FAILED,
			"provider": provider.id,
			"rolled_back": False,
			"result": result.as_dict(),
		}
	manifest.truncate_after(start)
	_persist_manifest(run, manifest)
	previous = completed[-2] if len(completed) > 1 else None
	capabilities = previous.capability_snapshot if previous else "{}"
	run.db_set("published_capabilities", capabilities or "{}", update_modified=False)
	_reset_step(step)
	for later in run.steps:
		if later.idx > step.idx and later.status == "Failed":
			_reset_step(later)
	run.db_set("status", STATUS_FAILED, update_modified=False)
	run.db_set("error", None, update_modified=False)
	frappe.db.commit()
	return {
		"run_id": run.name,
		"status": STATUS_FAILED,
		"provider": provider.id,
		"rolled_back": True,
		"result": result.as_dict(),
	}


def _reset_step(step: Any) -> None:
	for fieldname, value in {
		"status": "Pending",
		"started_at": None,
		"finished_at": None,
		"duration_ms": 0,
		"created_count": 0,
		"modified_count": 0,
		"manifest_start_sequence": -1,
		"checkpoint_sequence": -1,
		"input_fingerprint": None,
		"output_fingerprint": None,
		"capability_snapshot": None,
		"summary": None,
		"warnings": None,
		"error": None,
	}.items():
		frappe.db.set_value(step.doctype, step.name, fieldname, value, update_modified=False)
		step.set(fieldname, value)


def _fingerprint(payload: dict[str, Any]) -> str:
	encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
	return hashlib.sha256(encoded).hexdigest()


def phase_input_fingerprint(
	*, provider_id: str, provider_version: str, specification_hash_value: str, capabilities: dict[str, Any]
) -> str:
	return _fingerprint(
		{
			"provider": provider_id,
			"provider_version": provider_version,
			"specification_hash": specification_hash_value,
			"capabilities": capabilities,
		}
	)


def phase_output_fingerprint(
	*, provider_id: str, result: dict[str, Any], capabilities: dict[str, Any], records: list[dict[str, Any]]
) -> str:
	return _fingerprint(
		{"provider": provider_id, "result": result, "capabilities": capabilities, "records": records}
	)


def _describe_failure(provider: ScenarioProvider, exception: Exception) -> dict[str, Any]:
	if isinstance(exception, ScenarioError):
		payload = exception.as_dict()
		payload.setdefault("provider", provider.id)
		payload["provider"] = payload["provider"] or provider.id
	else:
		payload = {
			"code": "provider_exception",
			"message": str(exception),
			"provider": provider.id,
			"capability": None,
			"phase": "generate",
			"record": None,
			"details": {"exception_type": type(exception).__name__},
		}
	payload["traceback"] = traceback.format_exc(limit=25)
	return payload


def _serialisable(payload: dict[str, Any]) -> dict[str, Any]:
	safe: dict[str, Any] = {}
	for key, value in payload.items():
		try:
			json.dumps(value)
		except (TypeError, ValueError):
			continue
		safe[key] = value
	return safe


def _step_for(run: Any, provider_id: str) -> Any:
	for step in run.steps:
		if step.provider == provider_id:
			return step
	step = run.append("steps", {"provider": provider_id, "status": "Pending"})
	run.save(ignore_permissions=True)
	return step


def _update_step(run: Any, step: Any, **values: Any) -> None:
	for key, value in values.items():
		step.set(key, value)
		frappe.db.set_value(step.doctype, step.name, key, value, update_modified=False)


def _publish_progress(run_name: str, payload: dict[str, Any]) -> None:
	try:
		frappe.publish_realtime(
			"frappe_scenario_progress",
			{"run_id": run_name, **payload},
			user=frappe.session.user,
		)
	except Exception:  # pragma: no cover - realtime is best effort
		pass


# ---------------------------------------------------------------------------
# manifest persistence
# ---------------------------------------------------------------------------
def _persist_manifest(run: Any, manifest: Manifest) -> None:
	"""Store the detailed manifest as a private JSONL File attached to the run."""
	content = manifest.to_jsonl()
	filename = _manifest_filename(run.name)
	existing = frappe.db.get_value(
		"File",
		{
			"attached_to_doctype": RUN_DOCTYPE,
			"attached_to_name": run.name,
			"file_name": filename,
		},
		"name",
	)
	if existing:
		file_doc = frappe.get_doc("File", existing)
		file_doc.save_file(content=content, overwrite=True)
		file_doc.save(ignore_permissions=True)
	else:
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": filename,
				"attached_to_doctype": RUN_DOCTYPE,
				"attached_to_name": run.name,
				"is_private": 1,
				"content": content,
			}
		).insert(ignore_permissions=True)
	run.db_set("manifest_file", file_doc.file_url, update_modified=False)


def load_manifest(run: Any | str) -> Manifest:
	"""Read the manifest attached to a run."""
	if isinstance(run, str):
		run = frappe.get_doc(RUN_DOCTYPE, run)
	name = None
	# The legacy plain filename remains readable for existing installations.
	# New writes are run-specific so two live scenarios can never share file
	# content through Frappe's hash/file-url deduplication.
	for filename in (_manifest_filename(run.name), MANIFEST_FILENAME):
		name = frappe.db.get_value(
			"File",
			{
				"attached_to_doctype": RUN_DOCTYPE,
				"attached_to_name": run.name,
				"file_name": filename,
			},
			"name",
		)
		if name:
			break
	if not name:
		return Manifest()
	file_doc = frappe.get_doc("File", name)
	content = file_doc.get_content()
	if isinstance(content, bytes):
		content = content.decode("utf-8")
	return Manifest.from_jsonl(content)


# ---------------------------------------------------------------------------
# status, validation, cleanup
# ---------------------------------------------------------------------------
def get_status(run_name: str) -> dict[str, Any]:
	run = frappe.get_doc(RUN_DOCTYPE, run_name)
	stored_plan = json.loads(run.plan_json or "{}")
	return {
		"run_id": run.name,
		"title": run.title,
		"status": run.status,
		"cancellation_requested": bool(run.cancellation_requested),
		"approved": bool(run.approved),
		"archetype": run.archetype,
		"scale": run.scale,
		"country": run.country,
		"currency": run.currency,
		"company": run.company,
		"seed": run.seed,
		"anchor_date": str(run.anchor_date) if run.anchor_date else None,
		"specification_hash": run.specification_hash,
		"canonical_hash": run.canonical_hash,
		"structural_hash": run.structural_hash,
		"record_count": run.record_count,
		"estimated_records": run.estimated_records,
		"resource_estimate": stored_plan.get("resource_estimate") or {},
		"progress": {
			"completed_phases": sum(step.status == "Completed" for step in run.steps),
			"total_phases": len(run.steps),
			"current_phase": next(
				(step.provider for step in run.steps if step.status in ("Running", "Failed")), None
			),
		},
		"started_at": str(run.started_at) if run.started_at else None,
		"finished_at": str(run.finished_at) if run.finished_at else None,
		"manifest_file": run.manifest_file,
		"manifest_summary": json.loads(run.manifest_summary or "{}"),
		"validation_summary": json.loads(run.validation_summary or "{}"),
		"outcomes": json.loads(run.outcome_summary or "{}"),
		"quality_report": run.quality_report,
		"event_count": run.event_count,
		"warnings": json.loads(run.warnings or "[]"),
		"error": json.loads(run.error) if run.error else None,
		"steps": [
			{
				"provider": step.provider,
				"provider_version": step.provider_version,
				"status": step.status,
				"created": step.created_count,
				"modified": step.modified_count,
				"duration_ms": step.duration_ms,
				"checkpoint_sequence": step.checkpoint_sequence,
				"attempts": step.attempts,
				"input_fingerprint": step.input_fingerprint,
				"output_fingerprint": step.output_fingerprint,
				"error": json.loads(step.error) if step.error else None,
			}
			for step in run.steps
		],
	}


def validate_run(run_name: str) -> dict[str, Any]:
	"""Run every provider validator plus the core integrity validators."""
	run = frappe.get_doc(RUN_DOCTYPE, run_name)
	resolved = json.loads(run.specification)
	manifest = load_manifest(run)

	registry = discover_providers()
	graph = resolve_graph(registry, _requested_providers(resolved, registry))

	context = ScenarioContext(run_id=run.name, specification=resolved, manifest=manifest)
	context.restore_capabilities(json.loads(run.published_capabilities or "{}"), publisher="validate")

	result = ValidationResult()

	from frappe_scenario.validators import core_validators

	for validator in core_validators():
		context.current_provider = "frappe_scenario.core"
		result.extend(validator(context))

	for provider in graph.order:
		context.current_provider = provider.id
		try:
			result.extend(provider.validate(context))
		except Exception as exception:
			result.error(
				rule="validation.provider_exception",
				message=f"Validator for {provider.id} raised: {exception}",
				provider=provider.id,
			)

	skip = set((resolved.get("validation") or {}).get("skip_rules") or [])
	result = result.filtered(skip)

	_store_validation_results(run, result)
	summary = result.as_dict()
	run.db_set("validation_summary", json.dumps(summary, indent="\t", default=str), update_modified=False)
	from frappe_scenario.core.quality import assess_generated, persist_generated_report

	quality = assess_generated(
		specification=resolved,
		capabilities=context.published_capabilities,
		validation=summary,
		regional_records=_quality_regional_records(manifest),
	)
	quality["name"] = persist_generated_report(run, quality)
	frappe.db.commit()

	return {"run_id": run.name, "quality": quality, **summary}


def _quality_regional_records(manifest: Manifest) -> dict[str, list[dict[str, Any]]]:
	records: dict[str, list[dict[str, Any]]] = {"addresses": [], "contacts": []}
	for record in manifest.created():
		if record.doctype == "Address":
			value = frappe.db.get_value(
				"Address",
				record.name,
				["name", "address_line1", "city", "country"],
				as_dict=True,
			)
			if value:
				records["addresses"].append(dict(value))
		elif record.doctype == "Contact":
			value = frappe.db.get_value(
				"Contact",
				record.name,
				["name", "email_id"],
				as_dict=True,
			)
			if value:
				records["contacts"].append(dict(value))
	return records


def _store_validation_results(run: Any, result: ValidationResult) -> None:
	frappe.db.delete("Scenario Validation Result", {"scenario_run": run.name})
	for issue in result.issues:
		if issue.severity == "info":
			continue
		frappe.get_doc(
			{
				"doctype": "Scenario Validation Result",
				"scenario_run": run.name,
				"severity": issue.severity.title(),
				"rule": issue.rule,
				"provider": issue.provider,
				"capability": issue.capability,
				"reference_doctype": issue.doctype,
				"reference_name": issue.record,
				"message": issue.message,
				"remediation": issue.remediation,
			}
		).insert(ignore_permissions=True)


def cleanup_run(run_name: str, *, allow_non_disposable: bool = False) -> dict[str, Any]:
	"""Remove only this run's records and restore its setting changes."""
	assert_safe_to_generate(allow_non_disposable=allow_non_disposable)

	run = frappe.get_doc(RUN_DOCTYPE, run_name)
	manifest = load_manifest(run)
	if not len(manifest):
		run.db_set("status", STATUS_CLEANED, update_modified=False)
		frappe.db.commit()
		return {"run_id": run.name, "status": STATUS_CLEANED, "results": [], "blockers": []}

	resolved = json.loads(run.specification)
	registry = discover_providers()
	graph = resolve_graph(registry, _requested_providers(resolved, registry))

	context = ScenarioContext(run_id=run.name, specification=resolved, manifest=manifest)

	results: list[dict[str, Any]] = []
	blockers: list[dict[str, Any]] = []

	from frappe_scenario.core.troubleshooting import discard_lab_cases

	lab_blockers = discard_lab_cases(run.name)
	if lab_blockers:
		run.db_set("status", STATUS_FAILED, update_modified=False)
		run.db_set(
			"cleanup_summary",
			json.dumps({"results": [], "blockers": lab_blockers}, indent="\t", default=str),
			update_modified=False,
		)
		frappe.db.commit()
		return {"run_id": run.name, "status": STATUS_FAILED, "results": [], "blockers": lab_blockers}

	# A validation finding points at the document it was raised against, so the
	# run's own findings would otherwise hold that document in place.
	_discard_validation_results(run.name)
	# Narrative events use a Dynamic Link to their source ERPNext document.
	# Remove them before cleanup so the explanatory layer cannot pin business data.
	from frappe_scenario.core.narrative import discard_scenario_events

	discard_scenario_events(run.name)

	# A worker may finish (or fail) a valuation repost after generation failed.
	# Remove only reposts whose voucher, or item-and-warehouse pair, is owned by
	# this manifest before those non-manifest bookkeeping records pin its data.
	from frappe_scenario.core.cleanup import discard_owned_deferred_work

	deferred_blockers = discard_owned_deferred_work(list(manifest))
	if deferred_blockers:
		blockers.extend(deferred_blockers)

	# Reverse dependency order: the last provider to write is the first to clean.
	for provider in reversed(graph.order):
		# A live worker can finish a cancellation-generated valuation repost after
		# the initial sweep. Recheck before each provider so late bookkeeping cannot
		# pin an owned Item, Warehouse, voucher, or Company farther down the graph.
		late_deferred_blockers = discard_owned_deferred_work(list(manifest))
		if late_deferred_blockers:
			blockers.extend(late_deferred_blockers)
		records = manifest.for_provider(provider.id)
		if not records:
			continue
		context.current_provider = provider.id
		result = provider.cleanup(context, records)
		results.append(result.as_dict())
		blockers.extend(result.blockers)
		frappe.db.commit()

	orphans = [
		record for record in manifest if record.provider not in {provider.id for provider in graph.order}
	]
	if orphans:
		from frappe_scenario.core.cleanup import default_cleanup

		result = default_cleanup("frappe_scenario.orphans", orphans)
		results.append(result.as_dict())
		blockers.extend(result.blockers)
		frappe.db.commit()

	status = STATUS_CLEANED if not blockers else STATUS_FAILED
	run.db_set("status", status, update_modified=False)
	run.db_set(
		"cleanup_summary",
		json.dumps({"results": results, "blockers": blockers}, indent="\t", default=str),
		update_modified=False,
	)
	frappe.db.commit()

	return {"run_id": run.name, "status": status, "results": results, "blockers": blockers}


def _discard_validation_results(run_name: str) -> None:
	"""Remove the findings a run recorded, so they stop referencing its documents."""
	for name in frappe.get_all(VALIDATION_DOCTYPE, filters={"scenario_run": run_name}, pluck="name"):
		frappe.delete_doc(VALIDATION_DOCTYPE, name, ignore_permissions=True, delete_permanently=True)
	frappe.db.commit()


def export_run(run_name: str) -> dict[str, Any]:
	"""Everything needed to reproduce or review a run."""
	run = frappe.get_doc(RUN_DOCTYPE, run_name)
	manifest = load_manifest(run)
	return {
		"run_id": run.name,
		"exported_at": datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
		"specification": json.loads(run.specification),
		"specification_hash": run.specification_hash,
		"plan": json.loads(run.plan_json or "{}"),
		"assumptions": json.loads(run.assumptions or "[]"),
		"compatibility": json.loads(run.compatibility or "{}"),
		"status": run.status,
		"canonical_hash": run.canonical_hash,
		"structural_hash": run.structural_hash,
		"validation": json.loads(run.validation_summary or "{}"),
		"manifest": [record.as_dict() for record in manifest],
	}
