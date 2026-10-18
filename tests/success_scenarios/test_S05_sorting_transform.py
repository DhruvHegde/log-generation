"""Scenario S05: Sorting, transformations, and chunking."""
import pytest


def sort_records_by_priority_and_name(records):
    # Sort by priority ascending (1 is highest), then name alphabetically
    return sorted(records, key=lambda r: (r.get("priority", 999), r.get("name", "")))


def flatten_nested_dict(d, parent_key="", sep="."):
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_nested_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def chunk_list(lst, chunk_size):
    if chunk_size <= 0:
        raise ValueError("Chunk size must be positive.")
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]


def test_sort_records():
    records = [
        {"name": "Carol", "priority": 2},
        {"name": "Alice", "priority": 1},
        {"name": "Bob", "priority": 2},
        {"name": "David", "priority": 1},
    ]
    sorted_recs = sort_records_by_priority_and_name(records)
    names = [r["name"] for r in sorted_recs]
    assert names == ["Alice", "David", "Bob", "Carol"]


def test_flatten_dict():
    nested = {
        "pipeline": {
            "stage": "build",
            "runner": {"os": "ubuntu", "version": "latest"},
        },
        "enabled": True,
    }
    flattened = flatten_nested_dict(nested)
    assert flattened == {
        "pipeline.stage": "build",
        "pipeline.runner.os": "ubuntu",
        "pipeline.runner.version": "latest",
        "enabled": True,
    }


def test_chunk_list():
    items = list(range(10))
    chunks = chunk_list(items, 3)
    assert chunks == [[0, 1, 2], [3, 4, 5], [6, 7, 8], [9]]
    with pytest.raises(ValueError):
        chunk_list(items, 0)
