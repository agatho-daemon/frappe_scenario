# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Bench commands for the scenario platform.

Every command is a thin shell around :mod:`frappe_scenario.core.engine`, so the
CLI, the whitelisted API, and the desk all take exactly the same code path.

Run them as ``bench --site <site> scenario <command>``.
"""

from __future__ import annotations

import json
from typing import Any

import click
import frappe
from frappe.commands import get_site, pass_context


class ScenarioGroup(click.Group):
	"""Render structured scenario failures instead of a bare traceback.

	Every scenario error carries a provider, a phase, and a list of problems.
	Swallowing that structure and printing only the summary line would make the
	CLI strictly less useful than the API, so unpack it here.
	"""

	def invoke(self, ctx: click.Context) -> Any:
		from frappe_scenario.core.errors import ScenarioError

		try:
			return super().invoke(ctx)
		except ScenarioError as error:
			_echo_error(error)
			raise SystemExit(1) from error


def _blocker_line(blocker: Any) -> str:
	if isinstance(blocker, dict):
		return str(blocker.get("message") or blocker)
	return str(blocker)


def _echo_error(error: Any) -> None:
	click.echo(click.style(str(error), fg="red", bold=True), err=True)
	problems = error.details.get("problems") if isinstance(error.details, dict) else None
	if isinstance(problems, list):
		for problem in problems:
			if isinstance(problem, dict):
				location = problem.get("path") or problem.get("location") or ""
				prefix = f"{location}: " if location else ""
				click.echo(f"  - {prefix}{problem.get('message', problem)}", err=True)
			else:
				click.echo(f"  - {problem}", err=True)
	elif error.details:
		click.echo(json.dumps(error.details, indent="\t", default=str), err=True)


@click.group("scenario", cls=ScenarioGroup)
def scenario() -> None:
	"""Generate, validate, and clean up synthetic scenario datasets."""


# -- catalogue -----------------------------------------------------------------
@scenario.command("capabilities")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
@pass_context
def capabilities(context: Any, as_json: bool) -> None:
	"""List every discovered provider and the capabilities it offers."""
	with _site(context):
		from frappe_scenario.core.discovery import discover_providers, unavailable_providers

		registry = discover_providers()
		payload = {
			"providers": [provider.describe() for provider in registry.providers],
			"unavailable": unavailable_providers(),
		}

	if as_json:
		click.echo(json.dumps(payload, indent="\t", default=str))
		return

	for provider in payload["providers"]:
		click.echo(click.style(f"{provider['id']}  v{provider['version']}", bold=True))
		click.echo(f"  {provider['description']}")
		for capability in provider["capabilities"]:
			click.echo(f"    - {capability['id']}: {capability['description']}")
	for entry in payload["unavailable"]:
		label = entry.get("id") or entry.get("path")
		click.echo(click.style(f"{label}: unavailable ({entry['reason']})", fg="yellow"))


@scenario.command("describe")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
@pass_context
def describe(context: Any, as_json: bool) -> None:
	"""Describe the archetypes, country packs, and scales available."""
	with _site(context):
		from frappe_scenario.archetypes import describe_archetypes
		from frappe_scenario.core.scale import describe_scale_profiles
		from frappe_scenario.locales import describe_country_packs

		payload = {
			"archetypes": describe_archetypes(),
			"country_packs": describe_country_packs(),
			"scales": describe_scale_profiles(),
		}

	if as_json:
		click.echo(json.dumps(payload, indent="\t", default=str))
		return

	click.echo(click.style("Archetypes", bold=True))
	for archetype in payload["archetypes"]:
		click.echo(f"  {archetype['id']}: {archetype['title']} ({archetype['default_country']})")
	click.echo(click.style("Country packs", bold=True))
	for pack in payload["country_packs"]:
		click.echo(f"  {pack['id']}: {pack['country']} / {pack['currency']}")
	click.echo(click.style("Scales", bold=True))
	for name, profile in payload["scales"].items():
		click.echo(f"  {name}: {profile}")


# -- specification -------------------------------------------------------------
@scenario.command("validate-spec")
@click.argument("specification_file", type=click.Path(exists=True, dir_okay=False))
@pass_context
def validate_spec(context: Any, specification_file: str) -> None:
	"""Check a specification file against the schema without touching the site."""
	with _site(context):
		from frappe_scenario.core.specification import read_specification_file, validate_schema

		specification = read_specification_file(specification_file)
		problems = validate_schema(specification)

	if problems:
		click.echo(click.style("Specification failed schema validation.", fg="red", bold=True), err=True)
		for problem in problems:
			location = problem.get("path") or ""
			prefix = f"{location}: " if location else ""
			click.echo(f"  - {prefix}{problem.get('message', problem)}", err=True)
		raise SystemExit(1)

	click.echo(click.style("Specification is valid.", fg="green"))


@scenario.command("plan")
@click.argument("specification_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
@pass_context
def plan_command(context: Any, specification_file: str, as_json: bool) -> None:
	"""Show what a specification would create. Writes nothing."""
	with _site(context):
		from frappe_scenario.core import engine
		from frappe_scenario.core.specification import read_specification_file

		execution_plan = engine.plan(read_specification_file(specification_file))

	if as_json:
		click.echo(json.dumps(execution_plan, indent="\t", default=str))
		return

	scenario_section = execution_plan["specification"]["scenario"]
	click.echo(
		click.style(
			f"{scenario_section['archetype']} / {scenario_section.get('country')} / "
			f"{scenario_section['scale']} / seed {scenario_section['seed']}",
			bold=True,
		)
	)
	click.echo(f"Specification hash: {execution_plan['specification_hash']}")
	click.echo(f"Estimated records:  {execution_plan['estimated_records']}")
	click.echo("Execution order:")
	for provider_id in execution_plan["execution_order"]:
		click.echo(f"  - {provider_id}")
	_echo_list(
		"Assumptions",
		[
			f"{entry['path']} = {entry['value']} ({entry['reason']})"
			for entry in execution_plan["assumptions"]
		],
	)
	_echo_list("Unsupported", execution_plan["unsupported"], colour="yellow")
	_echo_blockers(execution_plan)


# -- execution -----------------------------------------------------------------
@scenario.command("run")
@click.argument("specification_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--title", help="Title for the run record.")
@click.option("--definition", help="Scenario Definition to link the run to.")
@click.option("--yes", is_flag=True, help="Approve the run without an interactive prompt.")
@click.option("--background", is_flag=True, help="Queue the run instead of executing it inline.")
@click.option(
	"--allow-non-disposable",
	is_flag=True,
	help="Generate on a site that is not marked disposable. Use with care.",
)
@pass_context
def run_command(
	context: Any,
	specification_file: str,
	title: str | None,
	definition: str | None,
	yes: bool,
	background: bool,
	allow_non_disposable: bool,
) -> None:
	"""Create, approve, and execute a run from a specification file."""
	with _site(context):
		from frappe_scenario.core import engine
		from frappe_scenario.core.specification import read_specification_file

		specification = read_specification_file(specification_file)
		execution_plan = engine.plan(specification, allow_non_disposable=allow_non_disposable)
		_echo_blockers(execution_plan)
		if execution_plan["blocked"] and not allow_non_disposable:
			raise click.ClickException("This site is not marked disposable; refusing to generate.")

		run_name = engine.create_run(specification, title=title, definition=definition)
		click.echo(f"Created run {click.style(run_name, bold=True)}.")

		if not yes:
			click.echo(f"It will create roughly {execution_plan['estimated_records']} records.")
			click.confirm("Approve and execute this run?", abort=True)

		engine.approve_run(run_name)

		if background:
			engine.enqueue_run(run_name, allow_non_disposable=allow_non_disposable)
			click.echo("Queued on the long queue. Follow it with `scenario status`.")
			return

		result = engine.execute_run(run_name, allow_non_disposable=allow_non_disposable)

	_echo_run_result(result)


@scenario.command("resume")
@click.argument("run_name")
@click.option("--allow-non-disposable", is_flag=True)
@pass_context
def resume_command(context: Any, run_name: str, allow_non_disposable: bool) -> None:
	"""Continue a failed run from its last successful provider."""
	with _site(context):
		from frappe_scenario.core import engine

		result = engine.resume_run(run_name, allow_non_disposable=allow_non_disposable)

	_echo_run_result(result)


@scenario.command("status")
@click.argument("run_name")
@click.option("--json", "as_json", is_flag=True)
@pass_context
def status_command(context: Any, run_name: str, as_json: bool) -> None:
	"""Show the current state of a run."""
	with _site(context):
		from frappe_scenario.core import engine

		payload = engine.get_status(run_name)

	if as_json:
		click.echo(json.dumps(payload, indent="\t", default=str))
		return

	click.echo(click.style(f"{payload['run_id']}  {payload['status']}", bold=True))
	click.echo(f"Records: {payload['record_count']} of about {payload['estimated_records']} estimated")
	click.echo(f"Canonical hash: {payload['canonical_hash'] or '-'}")
	for step in payload["steps"]:
		click.echo(
			f"  {step['status']:<10} {step['provider']:<28} "
			f"created {step['created']:>5}  modified {step['modified']:>5}"
		)
	if payload["error"]:
		click.echo(click.style(json.dumps(payload["error"], indent="\t"), fg="red"))


@scenario.command("validate")
@click.argument("run_name")
@click.option("--json", "as_json", is_flag=True)
@pass_context
def validate_command(context: Any, run_name: str, as_json: bool) -> None:
	"""Run the integrity and plausibility validators against a finished run."""
	with _site(context):
		from frappe_scenario.core import engine

		payload = engine.validate_run(run_name)

	if as_json:
		click.echo(json.dumps(payload, indent="\t", default=str))
		return

	counts = payload["counts"]
	colour = "green" if payload["passed"] else "red"
	click.echo(
		click.style(
			f"{'PASSED' if payload['passed'] else 'FAILED'}: "
			f"{counts.get('error', 0)} errors, {counts.get('warning', 0)} warnings, "
			f"{counts.get('info', 0)} notes",
			fg=colour,
			bold=True,
		)
	)
	for issue in payload["issues"]:
		if issue["severity"] == "info":
			continue
		click.echo(f"  [{issue['severity']}] {issue['rule']}: {issue['message']}")
		if issue.get("remediation"):
			click.echo(f"      -> {issue['remediation']}")

	if not payload["passed"]:
		raise click.exceptions.Exit(1)


@scenario.command("cleanup")
@click.argument("run_name")
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
@click.option("--allow-non-disposable", is_flag=True)
@pass_context
def cleanup_command(context: Any, run_name: str, yes: bool, allow_non_disposable: bool) -> None:
	"""Remove everything a run created, in reverse dependency order."""
	with _site(context):
		from frappe_scenario.core import engine

		if not yes:
			click.confirm(f"Delete every record created by {run_name}?", abort=True)
		payload = engine.cleanup_run(run_name, allow_non_disposable=allow_non_disposable)

	click.echo(click.style(f"{payload['run_id']}: {payload['status']}", bold=True))
	for result in payload["results"]:
		click.echo(
			f"  {result['provider']:<28} cancelled {result['cancelled']:>5}  "
			f"deleted {result['deleted']:>5}  restored {result['restored']:>5}"
		)
	for blocker in payload["blockers"]:
		click.echo(click.style(f"  blocked: {_blocker_line(blocker)}", fg="yellow"))
	if payload["blockers"]:
		raise click.exceptions.Exit(1)


@scenario.command("export")
@click.argument("run_name")
@click.option("--output", type=click.Path(dir_okay=False), help="Write to a file instead of stdout.")
@pass_context
def export_command(context: Any, run_name: str, output: str | None) -> None:
	"""Export a run's specification, plan, and manifest."""
	with _site(context):
		from frappe_scenario.core import engine

		payload = engine.export_run(run_name)

	encoded = json.dumps(payload, indent="\t", default=str)
	if output:
		with open(output, "w", encoding="utf-8") as handle:
			handle.write(encoded + "\n")
		click.echo(f"Wrote {output}.")
	else:
		click.echo(encoded)


# -- helpers -------------------------------------------------------------------
class _site:
	"""Connect to the site for the duration of a command."""

	def __init__(self, context: Any) -> None:
		self.context = context

	def __enter__(self) -> None:
		site = get_site(self.context)
		frappe.init(site=site)
		frappe.connect()
		frappe.set_user("Administrator")

	def __exit__(self, *exception: Any) -> None:
		frappe.destroy()


def _echo_list(heading: str, entries: list[str], colour: str | None = None) -> None:
	if not entries:
		return
	click.echo(click.style(heading, bold=True))
	for entry in entries:
		click.echo(click.style(f"  - {entry}", fg=colour) if colour else f"  - {entry}")


def _echo_blockers(execution_plan: dict[str, Any]) -> None:
	for blocker in execution_plan["safety"].get("blockers") or []:
		click.echo(click.style(f"Safety: {blocker}", fg="red"))


def _echo_run_result(result: dict[str, Any]) -> None:
	colour = "green" if result["status"] == "Completed" else "red"
	click.echo(click.style(f"{result['run_id']}: {result['status']}", fg=colour, bold=True))
	click.echo(f"Records created: {result.get('record_count', 0)}")
	if result.get("canonical_hash"):
		click.echo(f"Canonical hash:  {result['canonical_hash']}")
	for warning in result.get("warnings") or []:
		provider = warning.get("provider") if isinstance(warning, dict) else None
		prefix = f"{provider}: " if provider else ""
		click.echo(click.style(f"  warning: {prefix}{_blocker_line(warning)}", fg="yellow"))
	if result.get("error"):
		click.echo(click.style(json.dumps(result["error"], indent="\t"), fg="red"))
		raise click.exceptions.Exit(1)


commands = [scenario]
