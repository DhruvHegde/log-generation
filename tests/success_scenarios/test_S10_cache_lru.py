"""Scenario S10: In-memory LRU Cache implementation and validation."""
from collections import OrderedDict
import pytest


class LRUCache:
    def __init__(self, capacity: int):
        if capacity <= 0:
            raise ValueError("Capacity must be greater than zero.")
        self.capacity = capacity
        self.cache = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key):
        if key not in self.cache:
            self.misses += 1
            return None
        self.hits += 1
        self.cache.move_to_end(key)
        return self.cache[key]

    def put(self, key, value):
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)


def test_lru_cache_operations():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1
    assert cache.hits == 1

    # Insert "c", which should evict "b" because "a" was recently accessed
    cache.put("c", 3)
    assert cache.get("b") is None
    assert cache.misses == 1
    assert cache.get("a") == 1
    assert cache.get("c") == 3


def test_lru_invalid_capacity():
    with pytest.raises(ValueError):
        LRUCache(0)
    with pytest.raises(ValueError):
        LRUCache(-5)
