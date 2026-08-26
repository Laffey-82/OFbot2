import time

from app.core.cache import TTLCache


def test_ttl_cache_expiry_and_capacity() -> None:
    cache = TTLCache[int](max_size=2, default_ttl=0.05)
    cache.set("a", 1)
    assert cache.get("a") == 1
    time.sleep(0.06)
    assert cache.get("a") is None


def test_ttl_cache_evicts_oldest() -> None:
    cache = TTLCache[int](max_size=2, default_ttl=10)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)
    assert cache.get("a") is None
    assert cache.get("b") == 2
    assert cache.get("c") == 3

