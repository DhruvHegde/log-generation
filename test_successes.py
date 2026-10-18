import csv
import json
from pathlib import Path

import pytest

from automation.label_utils import LABEL_COLUMNS, append_label_record, ensure_label_file
from automation.validator import validate_success_workflow_log
import automation.workflow_utils as workflow_utils
import generate_successes


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _valid_log():
    return (
        "Compile Python Sources\n"
        "Python syntax/compilation checks passed\n"
        "Run Test Suite\n"
        "2 passed in 0.01s\n"
    )


def _workflow(commit_sha="abc123"):
    return {
        "databaseId": 12345678901,
        "headSha": commit_sha,
        "status": "completed",
        "conclusion": "success",
    }


# ---------------------------------------------------------------------------
# Validator tests
# ---------------------------------------------------------------------------

def test_success_log_validation_requires_compile_and_test_evidence():
    valid = validate_success_workflow_log(_valid_log())
    assert valid["status"] == "valid"
    assert "2 passed" in valid["validation_notes"]
    assert validate_success_workflow_log("2 passed in 0.01s")["status"] == "invalid"
    assert validate_success_workflow_log(
        "Compile Python Sources\nPython syntax/compilation checks passed\n"
        "Run Test Suite\n0 passed in 0.01s"
    )["status"] == "invalid"


# ---------------------------------------------------------------------------
# Workflow-polling tests
# ---------------------------------------------------------------------------

def test_workflow_polling_ignores_a_different_sha(monkeypatch):
    matching_run = _workflow()
    monkeypatch.setattr(
        workflow_utils,
        "get_workflow_runs",
        lambda: [
            {**matching_run, "headSha": "other"},
            matching_run,
        ],
    )
    monkeypatch.setattr(workflow_utils.time, "sleep", lambda _: None)

    assert workflow_utils.wait_for_run("abc123") == matching_run


# ---------------------------------------------------------------------------
# Metadata tests
# ---------------------------------------------------------------------------

def test_metadata_has_exact_required_schema_and_values():
    metadata = generate_successes._make_metadata(
        1,
        _workflow(),
        "abc123",
        "logs/success/F1/run_0001.log",
        "Python syntax/compilation checks passed; pytest reported 2 passed",
    )

    assert set(metadata) == set(generate_successes.METADATA_KEYS)
    assert len(metadata) == 16
    assert metadata["category_id"] is None
    assert metadata["failure_type"] is None
    assert metadata["workflow_id"] == 12345678901
    assert metadata["timestamp"].endswith("Z")


def test_metadata_rejects_a_workflow_for_another_sha():
    with pytest.raises(ValueError, match="exact commit"):
        generate_successes._make_metadata(
            1,
            _workflow(commit_sha="different"),
            "abc123",
            "logs/success/F1/run_0001.log",
            "checks passed",
        )


# ---------------------------------------------------------------------------
# Label / CSV tests
# ---------------------------------------------------------------------------

def test_label_writer_preserves_schema_and_prevents_duplicate_run_numbers(tmp_path):
    csv_path = tmp_path / "success_records.csv"
    ensure_label_file(csv_path)
    record = {
        "run_number": 1,
        "commit_sha": "abc123",
        "workflow_conclusion": "success",
    }

    assert append_label_record(csv_path, record) is True
    assert append_label_record(csv_path, record) is False
    with csv_path.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        rows = list(reader)
        assert reader.fieldnames == LABEL_COLUMNS
    assert len(rows) == 1
    assert rows[0]["failure_type"] == ""


def test_success_csv_mapping_records_the_dependency(tmp_path, monkeypatch):
    """dependency column is populated with the actual package spec."""
    monkeypatch.setattr(generate_successes, "REPO_NAME", "example")
    metadata = generate_successes._make_metadata(
        2,
        _workflow(),
        "abc123",
        "logs/success/F1/run_0002.log",
        "checks passed",
    )
    record = generate_successes._csv_record(2, "requests==2.31.0", metadata)

    assert tuple(record) == tuple(LABEL_COLUMNS)
    assert record["dependency"] == "requests==2.31.0"
    assert record["failure_type"] == ""
    assert record["workflow_conclusion"] == "success"
    assert record["stage"] == "ci"


# ---------------------------------------------------------------------------
# Dependency-list helpers
# ---------------------------------------------------------------------------

def test_load_success_dependencies_returns_non_comment_lines(tmp_path):
    dep_file = tmp_path / "success_dependencies.txt"
    dep_file.write_text(
        "# comment\n\nrequests==2.31.0\nurllib3==2.2.1\n# another comment\n",
        encoding="utf-8",
    )
    result = generate_successes.load_success_dependencies(str(dep_file))
    assert result == ["requests==2.31.0", "urllib3==2.2.1"]


def test_load_success_dependencies_raises_on_empty_file(tmp_path):
    dep_file = tmp_path / "empty.txt"
    dep_file.write_text("# only comments\n\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no usable dependency"):
        generate_successes.load_success_dependencies(str(dep_file))


def test_update_requirements_writes_only_the_dependency(tmp_path, monkeypatch):
    """requirements.txt must contain only the selected dependency — no pytest line."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "requirements.txt").write_text("old content\n", encoding="utf-8")
    generate_successes.update_requirements("requests==2.31.0")
    content = (tmp_path / "requirements.txt").read_text(encoding="utf-8")
    lines = [ln for ln in content.splitlines() if ln.strip()]
    assert lines == ["requests==2.31.0"], (
        f"requirements.txt must contain exactly the dependency, got: {lines}"
    )
    assert "pytest" not in content


# ---------------------------------------------------------------------------
# Recovery / idempotency tests
# ---------------------------------------------------------------------------

def test_recovery_finishes_csv_and_state_after_metadata_was_written(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(generate_successes, "SUCCESS_LOG_FOLDER", "logs/success/F1")
    monkeypatch.setattr(
        generate_successes, "SUCCESS_METADATA_FOLDER", "metadata/success/F1"
    )
    monkeypatch.setattr(generate_successes, "SUCCESS_CSV_FILE", "success_records.csv")
    monkeypatch.setattr(generate_successes, "SUCCESS_STATE_FILE", "success_state.json")
    monkeypatch.setattr(generate_successes, "SUCCESS_FAMILY", "F1")
    monkeypatch.setattr(generate_successes, "SUCCESS_SCENARIO", "valid_python_project")
    monkeypatch.setattr(generate_successes, "REPO_NAME", "example")

    log_file = Path("logs/success/F1/run_0001.log")
    log_file.parent.mkdir(parents=True)
    log_file.write_text(_valid_log(), encoding="utf-8")

    workflow = _workflow()
    pending = {
        "run_number": 1,
        "attempt_number": 1,
        "commit_message": "success attempt",
        "dependency": "requests==2.31.0",
        "commit_sha": "abc123",
        "workflow": workflow,
    }
    state = {
        "accepted_count": 0,
        "attempt_count": 1,
        "pending": pending,
    }
    generate_successes.save_state(state, "success_state.json")

    expected = generate_successes._make_metadata(
        1,
        workflow,
        "abc123",
        "logs/success/F1/run_0001.log",
        "Python syntax/compilation checks passed; pytest reported 2 passed",
    )
    expected["timestamp"] = "2026-10-18T08:00:00Z"
    metadata_path = Path("metadata/success/F1/run_0001.json")
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(json.dumps(expected), encoding="utf-8")

    assert generate_successes._process_successful_workflow(
        state,
        pending,
        workflow,
        "abc123",
    )
    recovered = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert set(recovered) == set(generate_successes.METADATA_KEYS)
    with open("success_records.csv", newline="", encoding="utf-8") as csv_file:
        records = list(csv.DictReader(csv_file))
    assert len(records) == 1
    assert records[0]["commit_sha"] == "abc123"
    assert records[0]["dependency"] == "requests==2.31.0"
    assert state["accepted_count"] == 1
    assert state["pending"] is None


def test_duplicate_csv_recovery_requires_matching_existing_record(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(generate_successes, "SUCCESS_CSV_FILE", "success_records.csv")
    monkeypatch.setattr(generate_successes, "REPO_NAME", "example")
    ensure_label_file("success_records.csv")
    metadata = generate_successes._make_metadata(
        1,
        _workflow(),
        "abc123",
        "logs/success/F1/run_0001.log",
        "checks passed",
    )
    generate_successes._persist_csv_record(1, "requests==2.31.0", metadata)
    generate_successes._persist_csv_record(1, "requests==2.31.0", metadata)
    with open("success_records.csv", newline="", encoding="utf-8") as csv_file:
        assert len(list(csv.DictReader(csv_file))) == 1

    metadata["commit_sha"] = "different"
    with pytest.raises(ValueError, match="does not match"):
        generate_successes._persist_csv_record(1, "requests==2.31.0", metadata)
