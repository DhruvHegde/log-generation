"""Scenario S07: Structured configuration and JSON payload validation."""
import json
import pytest


def parse_and_validate_manifest(json_str: str) -> dict:
    data = json.loads(json_str)
    required_keys = {"run_id", "status", "version"}
    if not required_keys.issubset(data.keys()):
        missing = required_keys - set(data.keys())
        raise ValueError(f"Missing required keys: {missing}")
    return data


def resolve_dotted_path(data: dict, path: str, default=None):
    keys = path.split(".")
    curr = data
    for k in keys:
        if isinstance(curr, dict) and k in curr:
            curr = curr[k]
        else:
            return default
    return curr


def test_manifest_validation():
    valid_payload = '{"run_id": "RUN_001", "status": "active", "version": "1.0", "extra": 42}'
    parsed = parse_and_validate_manifest(valid_payload)
    assert parsed["run_id"] == "RUN_001"
    assert parsed["status"] == "active"

    invalid_payload = '{"run_id": "RUN_002"}'
    with pytest.raises(ValueError):
        parse_and_validate_manifest(invalid_payload)


def test_resolve_dotted_path():
    cfg = {
        "database": {
            "connection": {
                "host": "localhost",
                "port": 5432
            }
        }
    }
    assert resolve_dotted_path(cfg, "database.connection.port") == 5432
    assert resolve_dotted_path(cfg, "database.connection.user", "default_user") == "default_user"
    assert resolve_dotted_path(cfg, "non.existent.path") is None
