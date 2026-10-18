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

def _valid_log(dependency="requests==2.31.0"):
    """Return a minimal but realistic GitHub Actions log for a success run.

    Includes the Install Selected Dependency step with a pip "Successfully
    installed" line, the Compile Python Sources step, and the Run Test Suite
    step.  All three are required for the validator to return "valid".
    """
    bare = dependency.split("==")[0].lower()
    return (
        f"dependency-test\tInstall Selected Dependency\t##[group]\n"
        f"dependency-test\tInstall Selected Dependency\tCollecting {dependency}\n"
        f"dependency-test\tInstall Selected Dependency\tSuccessfully installed {bare}-1.0\n"
        "dependency-test\tCompile Python Sources\tPython syntax/compilation checks passed\n"
        "dependency-test\tRun Test Suite\t2 passed in 0.01s\n"
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

def test_success_log_validation_requires_install_compile_and_test_evidence():
    """All three signals must be present for a valid result."""
    valid = validate_success_workflow_log(_valid_log(), dependency="requests==2.31.0")
    assert valid["status"] == "valid"
    assert "Dependency installation succeeded for requests==2.31.0" in valid["validation_notes"]
    assert "Python syntax/compilation checks passed" in valid["validation_notes"]
    assert "pytest reported 2 passed" in valid["validation_notes"]


def test_success_log_validation_fails_without_install_evidence():
    """Missing install step → invalid even if compile and tests pass."""
    log_no_install = (
        "dependency-test\tCompile Python Sources\tPython syntax/compilation checks passed\n"
        "dependency-test\tRun Test Suite\t5 passed in 0.02s\n"
    )
    result = validate_success_workflow_log(log_no_install, dependency="requests==2.31.0")
    assert result["status"] == "invalid"


def test_success_log_validation_fails_without_correct_package_in_install():
    """Successfully installed line must mention the requested package name."""
    log_wrong_pkg = (
        "dependency-test\tInstall Selected Dependency\tSuccessfully installed other-pkg-1.0\n"
        "dependency-test\tCompile Python Sources\tPython syntax/compilation checks passed\n"
        "dependency-test\tRun Test Suite\t1 passed in 0.01s\n"
    )
    result = validate_success_workflow_log(log_wrong_pkg, dependency="requests==2.31.0")
    assert result["status"] == "invalid"


def test_success_log_validation_skips_install_check_when_no_dependency():
    """When dependency=None the install check is skipped; compile+test suffice."""
    log_no_install_step = (
        "Compile Python Sources\n"
        "Python syntax/compilation checks passed\n"
        "Run Test Suite\n"
        "3 passed in 0.01s\n"
    )
    result = validate_success_workflow_log(log_no_install_step, dependency=None)
    assert result["status"] == "valid"
    assert "installation" not in result["validation_notes"].lower()


def test_success_log_validation_fails_without_compile_evidence():
    """Missing compile step → invalid."""
    assert validate_success_workflow_log(
        "dependency-test\tInstall Selected Dependency\tSuccessfully installed requests-2.31.0\n"
        "dependency-test\tRun Test Suite\t2 passed in 0.01s\n",
        dependency="requests==2.31.0",
    )["status"] == "invalid"


def test_success_log_validation_normalises_underscores_to_hyphens():
    """PEP 503: some_package spec must match some-package in pip output."""
    log = (
        "dependency-test\tInstall Selected Dependency\t##[group]\n"
        "dependency-test\tInstall Selected Dependency\tSuccessfully installed some-package-1.2.3\n"
        "dependency-test\tCompile Python Sources\tPython syntax/compilation checks passed\n"
        "dependency-test\tRun Test Suite\t1 passed in 0.01s\n"
    )
    result = validate_success_workflow_log(log, dependency="some_package==1.2.3")
    assert result["status"] == "valid", (
        "underscore spec should match hyphenated pip output via PEP 503 normalisation"
    )


def test_success_log_validation_rejects_substring_package_name():
    """'six' must not match 'six-another-1.0' — digit boundary required."""
    log = (
        "dependency-test\tInstall Selected Dependency\t##[group]\n"
        "dependency-test\tInstall Selected Dependency\tSuccessfully installed six-another-1.0\n"
        "dependency-test\tCompile Python Sources\tPython syntax/compilation checks passed\n"
        "dependency-test\tRun Test Suite\t1 passed in 0.01s\n"
    )
    result = validate_success_workflow_log(log, dependency="six==1.16.0")
    assert result["status"] == "invalid", (
        "'six' must not match 'six-another-1.0'"
    )


    """Zero tests passed → invalid."""
    assert validate_success_workflow_log(
        "dependency-test\tInstall Selected Dependency\tSuccessfully installed requests-2.31.0\n"
        "dependency-test\tCompile Python Sources\tPython syntax/compilation checks passed\n"
        "dependency-test\tRun Test Suite\t0 passed in 0.01s\n",
        dependency="requests==2.31.0",
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
        "Dependency installation succeeded for requests==2.31.0; "
        "Python syntax/compilation checks passed; pytest reported 2 passed",
        "requests==2.31.0",
    )

    assert set(metadata) == set(generate_successes.METADATA_KEYS)
    assert len(metadata) == 17
    assert metadata["dependency"] == "requests==2.31.0"
    assert metadata["category_id"] is None
    assert metadata["failure_type"] is None
    assert metadata["success_family"] == "F1"
    assert metadata["scenario_id"] == "successful_dependency_installation"
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
            "requests==2.31.0",
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


def test_success_csv_uses_build_stage_and_records_dependency(tmp_path, monkeypatch):
    """stage must be 'build' and dependency column must be populated."""
    monkeypatch.setattr(generate_successes, "REPO_NAME", "example")
    metadata = generate_successes._make_metadata(
        2,
        _workflow(),
        "abc123",
        "logs/success/F1/run_0002.log",
        "checks passed",
        "requests==2.31.0",
    )
    record = generate_successes._csv_record(2, "requests==2.31.0", metadata)

    assert tuple(record) == tuple(LABEL_COLUMNS)
    assert record["dependency"] == "requests==2.31.0"
    assert record["failure_type"] == ""
    assert record["workflow_conclusion"] == "success"
    assert record["stage"] == "build"


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


def test_ensure_attempt_commit_writes_only_dependency_to_requirements(tmp_path, monkeypatch):
    """End-to-end: _ensure_attempt_commit writes only the dependency to requirements.txt."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "requirements.txt").write_text("pytest>=8.0,<9.0\n", encoding="utf-8")

    captured_sha = "deadbeef1234"

    monkeypatch.setattr(
        generate_successes,
        "find_commit_by_message",
        lambda msg: None,
    )
    monkeypatch.setattr(
        generate_successes,
        "commit_and_push",
        lambda msg: captured_sha,
    )

    pending = {
        "run_number": 1,
        "attempt_number": 1,
        "commit_message": "Success dataset F1 run 0001 attempt 0001: requests==2.31.0",
        "dependency": "requests==2.31.0",
        "commit_sha": None,
        "workflow": None,
    }

    sha = generate_successes._ensure_attempt_commit(pending)

    assert sha == captured_sha
    assert pending["commit_sha"] == captured_sha

    content = (tmp_path / "requirements.txt").read_text(encoding="utf-8")
    lines = [ln for ln in content.splitlines() if ln.strip()]
    assert lines == ["requests==2.31.0"], (
        f"_ensure_attempt_commit wrote unexpected requirements.txt content: {lines}"
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
    monkeypatch.setattr(
        generate_successes, "SUCCESS_SCENARIO", "successful_dependency_installation"
    )
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
        "Dependency installation succeeded for requests==2.31.0; "
        "Python syntax/compilation checks passed; pytest reported 2 passed",
        "requests==2.31.0",
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
    assert len(recovered) == 17
    assert recovered["dependency"] == "requests==2.31.0"
    with open("success_records.csv", newline="", encoding="utf-8") as csv_file:
        records = list(csv.DictReader(csv_file))
    assert len(records) == 1
    assert records[0]["commit_sha"] == "abc123"
    assert records[0]["dependency"] == "requests==2.31.0"
    assert records[0]["stage"] == "build"
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
        "requests==2.31.0",
    )
    generate_successes._persist_csv_record(1, "requests==2.31.0", metadata)
    generate_successes._persist_csv_record(1, "requests==2.31.0", metadata)
    with open("success_records.csv", newline="", encoding="utf-8") as csv_file:
        assert len(list(csv.DictReader(csv_file))) == 1

    metadata["commit_sha"] = "different"
    with pytest.raises(ValueError, match="does not match"):
        generate_successes._persist_csv_record(1, "requests==2.31.0", metadata)
