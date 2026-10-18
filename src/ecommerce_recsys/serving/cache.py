"""Bounded, process-local snapshot results with insertion TTL and LRU eviction."""

from __future__ import annotations

import math
import sys
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from time import monotonic

from ecommerce_recsys.artifacts import Recommendation


def validate_cache_settings(max_entries, max_bytes, ttl_seconds):
    if type(max_entries) is not int or max_entries < 0:
        raise ValueError("Cache max_entries must be a nonnegative plain integer.")
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("Cache max_bytes must be a positive plain integer.")
    try:
        valid_ttl = (
            type(ttl_seconds) in (int, float) and math.isfinite(ttl_seconds) and ttl_seconds > 0
        )
    except OverflowError:
        valid_ttl = False
    if not valid_ttl:
        raise ValueError("Cache TTL must be finite and positive.")


@dataclass(frozen=True, slots=True)
class Entry:
    value: Recommendation
    deadline: float
    charge: int


def entry_charge(key, value):
    """Conservative entry accounting; excludes fixed container/allocator/RSS costs."""
    objects = (
        key,
        *key,
        value,
        value.items,
        *value.items,
        value.route,
        value.bundle_version,
        value.cutoff,
        0.0,
    )
    return 512 + sys.getsizeof(Entry(value, 0.0, 0)) + sum(sys.getsizeof(obj) for obj in objects)


class ResultCache:
    def __init__(
        self, namespace, *, max_entries, max_bytes, ttl_seconds, clock=monotonic, on_event=None
    ):
        validate_cache_settings(max_entries, max_bytes, ttl_seconds)
        if type(namespace) is not str or not 1 <= len(namespace) <= 128:
            raise ValueError("Cache requires a snapshot namespace.")
        self.namespace = namespace
        self.max_entries, self.max_bytes = max_entries, max_bytes
        self.ttl_seconds, self._clock = ttl_seconds, clock
        self._entries = OrderedDict()
        self._bytes = 0
        self._lock = Lock()
        self._counts = dict.fromkeys(("hits", "misses", "evictions", "expirations", "oversized"), 0)
        self._on_event = on_event

    def _count(self, event):
        self._counts[event] += 1
        if self._on_event is not None:
            try:
                self._on_event(event)
            except Exception:
                pass  # Observer failure cannot change cache semantics.

    def _remove(self, key):
        self._bytes -= self._entries.pop(key).charge

    def _expire(self, now):
        for key in [key for key, entry in self._entries.items() if entry.deadline <= now]:
            self._remove(key)
            self._count("expirations")

    def _key(self, user_id):
        if user_id is not None and (type(user_id) is not str or not 1 <= len(user_id) <= 128):
            raise ValueError("Cache contexts must be bounded string IDs or None.")
        return self.namespace, user_id

    def get(self, user_id):
        key = self._key(user_id)
        with self._lock:
            self._expire(self._clock())
            entry = self._entries.get(key)
            if entry is None:
                self._count("misses")
                return None
            self._entries.move_to_end(key)
            self._count("hits")
            return entry.value

    def put(self, user_id, value):
        if (
            type(value) is not Recommendation
            or type(value.items) is not tuple
            or len(value.items) > 20
            or any(type(item) is not str for item in value.items)
        ):
            raise ValueError("Cache accepts immutable snapshot recommendations only.")
        key = self._key(user_id)
        charge = entry_charge(key, value)
        with self._lock:
            now = self._clock()
            self._expire(now)
            if key in self._entries:
                self._remove(key)
            if not self.max_entries or charge > self.max_bytes:
                self._count("oversized")
                return False
            while len(self._entries) >= self.max_entries or self._bytes + charge > self.max_bytes:
                self._remove(next(iter(self._entries)))
                self._count("evictions")
            self._entries[key] = Entry(value, now + self.ttl_seconds, charge)
            self._bytes += charge
            return True

    def clear(self):
        with self._lock:
            self._entries.clear()
            self._bytes = 0

    def snapshot(self):
        with self._lock:
            return {"entries": len(self._entries), "charged_bytes": self._bytes, **self._counts}
