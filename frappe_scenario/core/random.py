# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Deterministic, namespaced randomness.

Rules enforced here:

* the global :mod:`random` state is never touched;
* every namespace receives a seed derived from the root seed, the provider id,
  and the logical namespace, so adding or reordering an unrelated provider
  cannot shift another provider's stream;
* Faker and numeric randomness share the derived namespace seed.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Sequence
from typing import Any, TypeVar

T = TypeVar("T")

_SEED_MODULUS = 1 << 63


def derive_seed(root_seed: int, *parts: str) -> int:
	"""Derive a stable 63-bit seed from the root seed and logical path parts."""
	payload = "\u0000".join([str(int(root_seed)), *[str(part) for part in parts]])
	digest = hashlib.blake2b(payload.encode("utf-8"), digest_size=8).digest()
	return int.from_bytes(digest, "big") % _SEED_MODULUS


class DeterministicRandom:
	"""A :class:`random.Random` wrapper with convenience helpers.

	The instance is isolated: it never reads or writes the global random state.
	"""

	def __init__(self, seed: int):
		self.seed = int(seed)
		self._random = random.Random(self.seed)

	# -- primitives ---------------------------------------------------------
	def random(self) -> float:
		return self._random.random()

	def randint(self, low: int, high: int) -> int:
		return self._random.randint(low, high)

	def uniform(self, low: float, high: float) -> float:
		return self._random.uniform(low, high)

	def choice(self, population: Sequence[T]) -> T:
		if not population:
			raise ValueError("choice() called with an empty population")
		return self._random.choice(population)

	def choices(self, population: Sequence[T], weights: Sequence[float] | None = None, k: int = 1) -> list[T]:
		return self._random.choices(population, weights=weights, k=k)

	def sample(self, population: Sequence[T], k: int) -> list[T]:
		return self._random.sample(list(population), k)

	def shuffled(self, population: Sequence[T]) -> list[T]:
		items = list(population)
		self._random.shuffle(items)
		return items

	# -- helpers ------------------------------------------------------------
	def chance(self, probability: float) -> bool:
		"""Return ``True`` with the given probability (0..1)."""
		return self._random.random() < float(probability)

	def rounded(self, low: float, high: float, precision: int = 2) -> float:
		return round(self._random.uniform(low, high), precision)

	def weighted_key(self, weights: dict[str, float]) -> str:
		"""Pick a key from a ``{key: weight}`` mapping using stable key ordering."""
		if not weights:
			raise ValueError("weighted_key() called with an empty mapping")
		keys = sorted(weights)
		values = [max(float(weights[key]), 0.0) for key in keys]
		if sum(values) <= 0:
			return keys[0]
		return self._random.choices(keys, weights=values, k=1)[0]

	def distribute(self, total: int, weights: dict[str, float]) -> dict[str, int]:
		"""Split ``total`` across weighted buckets using largest-remainder.

		The result is fully deterministic and always sums to ``total``.
		"""
		keys = sorted(weights)
		raw = [max(float(weights[key]), 0.0) for key in keys]
		weight_sum = sum(raw)
		if weight_sum <= 0:
			raise ValueError("distribute() requires at least one positive weight")
		exact = [value / weight_sum * total for value in raw]
		floors = [int(value) for value in exact]
		remainder = total - sum(floors)
		# Largest remainder first; ties broken by key order for determinism.
		order = sorted(range(len(keys)), key=lambda index: (-(exact[index] - floors[index]), keys[index]))
		for index in order[:remainder]:
			floors[index] += 1
		return dict(zip(keys, floors, strict=True))


class RandomService:
	"""Factory for namespaced deterministic random and Faker instances."""

	def __init__(self, root_seed: int, *, locales: Sequence[str] | None = None):
		self.root_seed = int(root_seed)
		self.locales = list(locales or ["en_US"])
		self._randoms: dict[tuple[str, str], DeterministicRandom] = {}
		self._fakers: dict[tuple[str, str, str], Any] = {}

	def random(self, provider_id: str, namespace: str = "default") -> DeterministicRandom:
		key = (provider_id, namespace)
		if key not in self._randoms:
			self._randoms[key] = DeterministicRandom(derive_seed(self.root_seed, provider_id, namespace))
		return self._randoms[key]

	def faker(self, provider_id: str, namespace: str = "default", locale: str | None = None) -> Any:
		"""Return a seeded Faker bound to the same derived namespace seed."""
		from faker import Faker

		resolved_locale = locale or self.locales[0]
		key = (provider_id, namespace, resolved_locale)
		if key not in self._fakers:
			instance = Faker(resolved_locale)
			instance.seed_instance(derive_seed(self.root_seed, provider_id, namespace))
			self._fakers[key] = instance
		return self._fakers[key]

	def fingerprint(self) -> dict[str, Any]:
		"""Library fingerprint recorded in the manifest.

		Faker's word lists and provider algorithms change between releases, so a
		logical hash is only comparable across sites running the same fingerprint.
		"""
		import faker

		return {"faker": getattr(faker, "VERSION", "unknown"), "locales": list(self.locales)}
