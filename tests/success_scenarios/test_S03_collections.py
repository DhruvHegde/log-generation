"""Scenario S03: Collection operations, grouping, and deduplication."""
from collections import Counter, defaultdict
import pytest


def deduplicate_keep_order(items):
    seen = set()
    result = []
    for x in items:
        if x not in seen:
            seen.add(x)
            result.append(x)
    return result


def group_by_key(items, key_func):
    grouped = defaultdict(list)
    for item in items:
        grouped[key_func(item)].append(item)
    return dict(grouped)


def deep_merge(d1: dict, d2: dict) -> dict:
    result = dict(d1)
    for k, v in d2.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def test_deduplication():
    assert deduplicate_keep_order([1, 2, 2, 3, 1, 4, 3, 5]) == [1, 2, 3, 4, 5]
    assert deduplicate_keep_order([]) == []
    assert deduplicate_keep_order(["a", "b", "a"]) == ["a", "b"]


def test_grouping():
    words = ["apple", "banana", "apricot", "cherry", "blueberry"]
    grouped = group_by_key(words, lambda w: w[0])
    assert grouped["a"] == ["apple", "apricot"]
    assert grouped["b"] == ["banana", "blueberry"]
    assert grouped["c"] == ["cherry"]


def test_deep_merge():
    base = {"a": 1, "b": {"x": 10, "y": 20}}
    override = {"b": {"y": 30, "z": 40}, "c": 5}
    merged = deep_merge(base, override)
    assert merged == {"a": 1, "b": {"x": 10, "y": 30, "z": 40}, "c": 5}
