# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Pure regression tests for the Bench command boundary."""

from pathlib import Path
from types import SimpleNamespace

import click
import pytest

from frappe_scenario import commands

pytestmark = pytest.mark.pure


def test_specification_path_resolves_from_the_bench_root(monkeypatch, tmp_path):
	specification = tmp_path / "apps" / "frappe_scenario" / "examples" / "scenario.json"
	specification.parent.mkdir(parents=True)
	specification.write_text("{}", encoding="utf-8")
	sites = tmp_path / "sites"
	sites.mkdir()

	monkeypatch.chdir(sites)
	monkeypatch.setattr(commands.frappe.utils, "get_bench_path", lambda: str(tmp_path))

	assert commands._resolve_specification_file(
		"apps/frappe_scenario/examples/scenario.json"
	) == str(specification)


def test_specification_path_accepts_absolute_and_current_directory_paths(monkeypatch, tmp_path):
	specification = tmp_path / "scenario.json"
	specification.write_text("{}", encoding="utf-8")
	monkeypatch.chdir(tmp_path)
	monkeypatch.setattr(commands.frappe.utils, "get_bench_path", lambda: str(tmp_path / "bench"))

	assert commands._resolve_specification_file("scenario.json") == str(specification)
	assert commands._resolve_specification_file(str(specification)) == str(specification)


def test_missing_specification_path_reports_both_search_locations(monkeypatch, tmp_path):
	monkeypatch.chdir(tmp_path)
	monkeypatch.setattr(commands.frappe.utils, "get_bench_path", lambda: str(tmp_path / "bench"))

	with pytest.raises(click.BadParameter, match="current directory or Bench root"):
		commands._resolve_specification_file("missing.json")


@pytest.mark.parametrize(
	("selection_kind", "selected_site"),
	[("default", "default.local"), ("explicit", "explicit.local")],
)
def test_site_context_uses_frappes_selected_default_or_explicit_site(
	monkeypatch, selection_kind, selected_site
):
	# Frappe's outer Bench command resolves either selection into ``sites``.
	# The scenario command must consume that resolved value without replacing it.
	context = SimpleNamespace(sites=[selected_site], selection_kind=selection_kind)
	seen = []

	monkeypatch.setattr(commands.frappe, "init", lambda *, site: seen.append(("init", site)))
	monkeypatch.setattr(commands.frappe, "connect", lambda: seen.append(("connect", None)))
	monkeypatch.setattr(commands.frappe, "set_user", lambda user: seen.append(("user", user)))
	monkeypatch.setattr(commands.frappe, "destroy", lambda: seen.append(("destroy", None)))

	with commands._site(context):
		pass

	assert seen == [
		("init", selected_site),
		("connect", None),
		("user", "Administrator"),
		("destroy", None),
	]
