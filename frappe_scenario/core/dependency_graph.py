# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Capability dependency resolution.

Ordering is a deterministic topological sort. Ties are broken by ``order`` then
provider id so that the same registry always produces the same execution order,
regardless of hook declaration order or dictionary iteration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from frappe_scenario.core.discovery import ProviderRegistry
from frappe_scenario.core.errors import DependencyError
from frappe_scenario.core.provider import ScenarioProvider


@dataclass
class ResolvedGraph:
	order: list[ScenarioProvider] = field(default_factory=list)
	edges: list[tuple[str, str]] = field(default_factory=list)
	satisfied_optional: dict[str, list[str]] = field(default_factory=dict)
	missing_optional: dict[str, list[str]] = field(default_factory=dict)

	def as_dict(self) -> dict[str, Any]:
		return {
			"order": [provider.id for provider in self.order],
			"edges": [{"from": source, "to": target} for source, target in self.edges],
			"satisfied_optional": dict(self.satisfied_optional),
			"missing_optional": dict(self.missing_optional),
		}


def _select(registry: ProviderRegistry, requested: set[str] | None) -> list[ScenarioProvider]:
	"""Select the requested providers plus everything they transitively require."""
	if requested is None:
		return registry.providers

	selected: dict[str, ScenarioProvider] = {}
	pending = list(requested)
	while pending:
		provider_id = pending.pop()
		if provider_id in selected:
			continue
		provider = registry.get(provider_id)
		selected[provider_id] = provider
		for capability in provider.requires_capabilities:
			owner = registry.owner_of(capability)
			if owner is None:
				raise DependencyError(
					f"Capability {capability!r} required by {provider_id!r} is not provided by any "
					"installed app.",
					provider=provider_id,
					capability=capability,
					phase="plan",
					details={"available": sorted(registry.capability_owners)},
				)
			pending.append(owner)
		for other_id in provider.runs_after:
			if other_id in registry:
				pending.append(other_id)
	return [selected[key] for key in sorted(selected)]


def resolve_graph(registry: ProviderRegistry, requested: set[str] | None = None) -> ResolvedGraph:
	"""Resolve provider execution order or explain why it is impossible."""
	providers = _select(registry, requested)
	by_id = {provider.id: provider for provider in providers}

	edges: list[tuple[str, str]] = []
	incoming: dict[str, set[str]] = {provider.id: set() for provider in providers}
	graph = ResolvedGraph()

	for provider in providers:
		for capability in sorted(provider.requires_capabilities):
			owner = registry.owner_of(capability)
			if owner is None:
				raise DependencyError(
					f"Capability {capability!r} required by {provider.id!r} is not available.",
					provider=provider.id,
					capability=capability,
					phase="plan",
					details={"available": sorted(registry.capability_owners)},
				)
			if owner not in by_id:
				raise DependencyError(
					f"Provider {owner!r} owns required capability {capability!r} but was excluded "
					"from this run.",
					provider=provider.id,
					capability=capability,
					phase="plan",
				)
			if owner != provider.id:
				edges.append((owner, provider.id))
				incoming[provider.id].add(owner)

		satisfied: list[str] = []
		missing: list[str] = []
		for capability in sorted(provider.optional_capabilities):
			owner = registry.owner_of(capability)
			if owner and owner in by_id:
				satisfied.append(capability)
				if owner != provider.id:
					edges.append((owner, provider.id))
					incoming[provider.id].add(owner)
			else:
				missing.append(capability)
		if satisfied:
			graph.satisfied_optional[provider.id] = satisfied
		if missing:
			graph.missing_optional[provider.id] = missing

		for other_id in sorted(provider.runs_after):
			if other_id in by_id and other_id != provider.id:
				edges.append((other_id, provider.id))
				incoming[provider.id].add(other_id)

	# Deterministic Kahn's algorithm.
	ready = sorted(
		(pid for pid, sources in incoming.items() if not sources),
		key=lambda pid: (by_id[pid].order, pid),
	)
	ordered: list[str] = []
	remaining = {pid: set(sources) for pid, sources in incoming.items()}

	while ready:
		current = ready.pop(0)
		ordered.append(current)
		released: list[str] = []
		for pid, sources in remaining.items():
			if current in sources:
				sources.discard(current)
				if not sources and pid not in ordered and pid not in ready:
					released.append(pid)
		ready = sorted(set(ready) | set(released), key=lambda pid: (by_id[pid].order, pid))

	if len(ordered) != len(by_id):
		blocked = sorted(set(by_id) - set(ordered))
		raise DependencyError(
			"Provider dependency cycle detected.",
			phase="plan",
			details={
				"blocked_providers": blocked,
				"unresolved_edges": [
					{"from": source, "to": target}
					for source, target in edges
					if target in blocked and source in blocked
				],
			},
		)

	graph.order = [by_id[pid] for pid in ordered]
	graph.edges = sorted(set(edges))
	return graph
