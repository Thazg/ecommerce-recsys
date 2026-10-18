"""Cache expiry, identity, eviction and entry-budget behavior."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError

import pytest

from ecommerce_recsys.artifacts import Recommendation
from ecommerce_recsys.serving.cache import ResultCache, entry_charge


def value(*items):
    return Recommendation(tuple(items), "hybrid_learned", "snapshot", 99)


def test_ttl_is_insertion_based_and_expires_at_boundary():
    now = [10.0]
    cache = ResultCache("n", max_entries=3, max_bytes=100000, ttl_seconds=5, clock=lambda: now[0])
    cache.put("u", value("a"))
    now[0] = 14.9
    assert cache.get("u") == value("a")
    now[0] = 15.0
    assert cache.get("u") is None
    assert cache.snapshot()["expirations"] == 1


def test_lru_eviction_and_cold_context_are_distinct():
    cache = ResultCache("n", max_entries=2, max_bytes=100000, ttl_seconds=5)
    cache.put(None, value("cold"))
    cache.put("u", value("a"))
    assert cache.get(None).items == ("cold",)
    cache.put("v", value("b"))
    assert cache.get("u") is None and cache.get("v").items == ("b",)
    assert cache.snapshot()["evictions"] == 1


def test_entry_budget_oversize_clear_and_namespace_isolation():
    cost = entry_charge(("n", "u"), value("a"))
    cache = ResultCache("n", max_entries=10, max_bytes=cost, ttl_seconds=10)
    assert cache.put("u", value("a"))
    assert cache.snapshot()["charged_bytes"] == cost
    assert cache.put("v", value("b"))
    assert cache.get("u") is None
    assert not cache.put("z", value("x" * 128))
    assert cache.snapshot()["oversized"] == 1
    other = ResultCache("other", max_entries=10, max_bytes=10000, ttl_seconds=10)
    assert other.get("v") is None
    stored = cache.get("v")
    with pytest.raises(FrozenInstanceError):
        stored.items = ("tampered",)
    cache.clear()
    assert cache.get("v") is None and cache.snapshot()["charged_bytes"] == 0


def test_concurrent_reads_writes_remain_within_both_limits():
    cache = ResultCache("n", max_entries=7, max_bytes=10000, ttl_seconds=30)

    def work(index):
        for i in range(20):
            cache.put(str(index * 20 + i), value(str(i)))
            cache.get(str(index * 20 + i))
            state = cache.snapshot()
            assert 0 <= state["entries"] <= 7 and 0 <= state["charged_bytes"] <= 10000

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(work, range(4)))


@pytest.mark.parametrize(
    "args",
    [
        {"max_entries": True},
        {"max_entries": -1},
        {"max_bytes": 0},
        {"ttl_seconds": float("nan")},
        {"ttl_seconds": float("inf")},
        {"ttl_seconds": True},
        {"ttl_seconds": 0},
        {"ttl_seconds": 10**1000},
    ],
)
def test_invalid_settings_fail_at_construction(args):
    with pytest.raises(ValueError):
        ResultCache("n", **({"max_entries": 1, "max_bytes": 10000, "ttl_seconds": 10} | args))


def test_disabled_or_too_small_cache_does_not_grow():
    for entries, size in ((0, 10000), (5, 1)):
        cache = ResultCache("n", max_entries=entries, max_bytes=size, ttl_seconds=10)
        assert not cache.put("u", value("a"))
        assert cache.snapshot()["entries"] == cache.snapshot()["charged_bytes"] == 0
