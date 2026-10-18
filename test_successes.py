import csv
import json
from pathlib import Path
import subprocess

import pytest

from automation.label_utils import LABEL_COLUMNS, append_label_record, ensure_label_file
from automation.validator import validate_success_workflow_log
import automation.git_utils as git_utils
import automation.workflow_utils as workflow_utils
import generate_successes


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _valid_log(dependency="requests==2.31.0"):
    """Return a minimal GitHub Actions log showing a successful installation.

    Contains only the Install Selected Dependency step — no compile or test
    steps are present or required by the validator.
    """
    bare = dependency.split("==")[0].lower()
    return (
        f"dependency-test\tInstall Selected Dependency\t##[group]\n"
        f"dependency-test\tInstall Selected Dependency\tCollecting {dependency}\n"
        f"dependency-test\tInstall Selected Dependency\t"
        f"Successfully installed {bare}-1.0\n"
    )


def _workflow(commit_sha="abc123"):
    return {
        "databaseId": 12345678901,
        "headSha": commit_sha,
        "status": "completed",
        "conclusion": "success",
    }


# ---------------------------------------------------------------------------
# Validator — happy-path tests
# ---------------------------------------------------------------------------

def test_validator_accepts_successful_installation():
    """A valid log with the correct package in 'Successfully installed' is accepted."""
    result = validate_success_workflow_log(
        _valid_log("requests==2.31.0"), dependency="requests==2.31.0"
    )
    assert result["status"] == "valid"
    assert "Dependency installation succeeded for requests==2.31.0" in result["validation_notes"]
    assert result["matched_line"] is not None
    assert "successfully installed" in result["matched_line"].lower()
    assert "requests" in result["matched_line"].lower()


def test_validator_returns_stripped_pip_line_without_log_prefix():
    """matched_line must be the pip text only, with any log timestamp removed."""
    log = (
        "dependency-test\tInstall Selected Dependency\t"
        "2026-01-01T00:00:00Z "
        "Successfully installed requests-2.31.0 certifi-2024.1\n"
    )
    result = validate_success_workflow_log(log, dependency="requests==2.31.0")
    assert result["status"] == "valid"
    assert result["matched_line"] == "Successfully installed requests-2.31.0 certifi-2024.1"


def test_validator_accepts_requirement_already_satisfied_with_exact_version():
    """'Requirement already satisfied' is valid when name+version match the spec."""
    log = (
        "dependency-test\tInstall Selected Dependency\t"
        "Requirement already satisfied: urllib3==2.2.1 in /path "
        "(from -r requirements.txt (line 1))\n"
    )
    result = validate_success_workflow_log(log, dependency="urllib3==2.2.1")
    assert result["status"] == "valid"
    assert result["matched_line"] is not None
    assert "Requirement already satisfied" in result["matched_line"]


def test_validator_normalises_underscores_to_hyphens():
    """PEP 503: some_package spec must match some-package in pip output."""
    log = (
        "dependency-test\tInstall Selected Dependency\t##[group]\n"
        "dependency-test\tInstall Selected Dependency\t"
        "Successfully installed some-package-1.2.3\n"
    )
    result = validate_success_workflow_log(log, dependency="some_package==1.2.3")
    assert result["status"] == "valid"


def test_validator_normalises_dots_to_hyphens():
    """PEP 503: some.package spec must match some-package in pip output."""
    log = (
        "dependency-test\tInstall Selected Dependency\t"
        "Successfully installed some-package-1.0\n"
    )
    result = validate_success_workflow_log(log, dependency="some.package==1.0")
    assert result["status"] == "valid"


def test_validator_normalises_mixed_case():
    """PyNaCl spec must match pynacl in pip output."""
    log = (
        "dependency-test\tInstall Selected Dependency\t"
        "Successfully installed pynacl-1.5.0\n"
    )
    result = validate_success_workflow_log(log, dependency="PyNaCl==1.5.0")
    assert result["status"] == "valid"


# ---------------------------------------------------------------------------
# Validator — rejection tests
# ---------------------------------------------------------------------------

def test_validator_rejects_empty_log():
    assert validate_success_workflow_log("", dependency="requests==2.31.0")["status"] == "invalid"
    assert validate_success_workflow_log(None, dependency="requests==2.31.0")["status"] == "invalid"


def test_validator_rejects_collecting_without_successfully_installed():
    """'Collecting' alone is not proof of installation success."""
    log = (
        "dependency-test\tInstall Selected Dependency\tCollecting requests==2.31.0\n"
        "dependency-test\tInstall Selected Dependency\t  Downloading requests-2.31.0.whl\n"
    )
    result = validate_success_workflow_log(log, dependency="requests==2.31.0")
    assert result["status"] == "invalid"


def test_validator_rejects_wrong_package_in_install_line():
    """'Successfully installed' must name the requested package."""
    log = (
        "dependency-test\tInstall Selected Dependency\t"
        "Successfully installed other-pkg-1.0\n"
    )
    result = validate_success_workflow_log(log, dependency="requests==2.31.0")
    assert result["status"] == "invalid"


def test_validator_rejects_substring_package_name():
    """'six' must not match 'six-another-1.0' — digit boundary required."""
    log = (
        "dependency-test\tInstall Selected Dependency\t"
        "Successfully installed six-another-1.0\n"
    )
    result = validate_success_workflow_log(log, dependency="six==1.16.0")
    assert result["status"] == "invalid"


def test_validator_rejects_requirement_already_satisfied_wrong_version():
    """'Requirement already satisfied' for a different version must be rejected."""
    log = (
        "dependency-test\tInstall Selected Dependency\t"
        "Requirement already satisfied: urllib3==1.26.0 in /path\n"
    )
    result = validate_success_workflow_log(log, dependency="urllib3==2.2.1")
    assert result["status"] == "invalid"


def test_validator_rejects_requirement_already_satisfied_superset_name():
    """'six' must not match 'six-tools==1.16.0' in Requirement already satisfied."""
    log = (
        "dependency-test\tInstall Selected Dependency\t"
        "Requirement already satisfied: six-tools==1.16.0 in /path\n"
    )
    result = validate_success_workflow_log(log, dependency="six==1.16.0")
    assert result["status"] == "invalid"


def test_validator_accepts_requirement_already_satisfied_with_normalised_name():
    """python_dateutil spec must match python-dateutil in Requirement already satisfied."""
    log = (
        "dependency-test\tInstall Selected Dependency\t"
        "Requirement already satisfied: python-dateutil==2.9.0 in /path\n"
    )
    result = validate_success_workflow_log(log, dependency="python_dateutil==2.9.0")
    assert result["status"] == "valid"
    assert result["matched_line"] is not None
    assert "python-dateutil" in result["matched_line"].lower()


def test_validator_rejects_requirement_already_satisfied_outside_install_step():
    """Requirement already satisfied in a different step must not satisfy the check."""
    log = (
        "dependency-test\tSome Other Step\t"
        "Requirement already satisfied: urllib3==2.2.1 in /path\n"
    )
    result = validate_success_workflow_log(log, dependency="urllib3==2.2.1")
    assert result["status"] == "invalid"


def test_validator_rejects_install_evidence_outside_install_step():
    """'Successfully installed' in a different step must not satisfy the check."""
    log = (
        "dependency-test\tSome Other Step\t"
        "Successfully installed requests-2.31.0\n"
    )
    result = validate_success_workflow_log(log, dependency="requests==2.31.0")
    assert result["status"] == "invalid"


def test_validator_does_not_require_compile_or_test_evidence():
    """Compile or pytest lines in the log do not affect validation outcome."""
    log_with_extra = (
        _valid_log("requests==2.31.0")
        + "dependency-test\tCompile Python Sources\tPython syntax/compilation checks passed\n"
        "dependency-test\tRun Test Suite\t5 passed in 0.01s\n"
    )
    log_without_extra = _valid_log("requests==2.31.0")
    assert validate_success_workflow_log(log_with_extra,   dependency="requests==2.31.0")["status"] == "valid"
    assert validate_success_workflow_log(log_without_extra, dependency="requests==2.31.0")["status"] == "valid"


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
        "Dependency installation succeeded for requests==2.31.0",
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


def test_success_csv_uses_build_stage_and_records_matched_line(tmp_path, monkeypatch):
    """stage is 'build', dependency is populated, matched_pattern holds the pip line."""
    monkeypatch.setattr(generate_successes, "REPO_NAME", "example")
    metadata = generate_successes._make_metadata(
        2,
        _workflow(),
        "abc123",
        "logs/success/F1/run_0002.log",
        "Dependency installation succeeded for requests==2.31.0",
        "requests==2.31.0",
    )
    matched = "Successfully installed requests-2.31.0 certifi-2024.1"
    record = generate_successes._csv_record(2, "requests==2.31.0", metadata, matched)

    assert tuple(record) == tuple(LABEL_COLUMNS)
    assert record["dependency"] == "requests==2.31.0"
    assert record["failure_type"] == ""
    assert record["workflow_conclusion"] == "success"
    assert record["stage"] == "build"
    assert record["matched_pattern"] == matched


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
    """requirements.txt must contain only the selected dependency."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "requirements.txt").write_text("old content\n", encoding="utf-8")
    generate_successes.update_requirements("requests==2.31.0")
    content = (tmp_path / "requirements.txt").read_text(encoding="utf-8")
    lines = [ln for ln in content.splitlines() if ln.strip()]
    assert lines == ["requests==2.31.0"]
    assert "pytest" not in content


def test_ensure_attempt_commit_writes_only_dependency_to_requirements(tmp_path, monkeypatch):
    """_ensure_attempt_commit writes only the dependency — no pytest line."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "requirements.txt").write_text("old\n", encoding="utf-8")

    monkeypatch.setattr(generate_successes, "find_commit_by_message", lambda msg: None)
    monkeypatch.setattr(generate_successes, "commit_and_push", lambda msg: "deadbeef")

    pending = {
        "run_number": 1,
        "attempt_number": 1,
        "commit_message": "Success dataset F1 run 0001 attempt 0001: requests==2.31.0",
        "dependency": "requests==2.31.0",
        "commit_sha": None,
        "workflow": None,
    }
    sha = generate_successes._ensure_attempt_commit(pending)
    assert sha == "deadbeef"
    content = (tmp_path / "requirements.txt").read_text(encoding="utf-8")
    assert [ln for ln in content.splitlines() if ln.strip()] == ["requests==2.31.0"]
    assert "pytest" not in content


# ---------------------------------------------------------------------------
# Recovery / idempotency tests
# ---------------------------------------------------------------------------

def test_recovery_finishes_csv_and_state_after_metadata_was_written(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(generate_successes, "SUCCESS_LOG_FOLDER", "logs/success/F1")
    monkeypatch.setattr(generate_successes, "SUCCESS_METADATA_FOLDER", "metadata/success/F1")
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
    state = {"accepted_count": 0, "attempt_count": 1, "pending": pending}
    generate_successes.save_state(state, "success_state.json")

    expected = generate_successes._make_metadata(
        1,
        workflow,
        "abc123",
        "logs/success/F1/run_0001.log",
        "Dependency installation succeeded for requests==2.31.0",
        "requests==2.31.0",
    )
    expected["timestamp"] = "2026-10-18T08:00:00Z"
    metadata_path = Path("metadata/success/F1/run_0001.json")
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(json.dumps(expected), encoding="utf-8")

    assert generate_successes._process_successful_workflow(
        state, pending, workflow, "abc123"
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
    assert "successfully installed" in records[0]["matched_pattern"].lower()
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
        "Dependency installation succeeded for requests==2.31.0",
        "requests==2.31.0",
    )
    matched = "Successfully installed requests-2.31.0"
    generate_successes._persist_csv_record(1, "requests==2.31.0", metadata, matched)
    generate_successes._persist_csv_record(1, "requests==2.31.0", metadata, matched)
    with open("success_records.csv", newline="", encoding="utf-8") as csv_file:
        assert len(list(csv.DictReader(csv_file))) == 1

    metadata["commit_sha"] = "different"
    with pytest.raises(ValueError, match="does not match"):
        generate_successes._persist_csv_record(1, "requests==2.31.0", metadata, matched)


# ---------------------------------------------------------------------------
# Commit-path and error-reporting tests
# ---------------------------------------------------------------------------

def test_git_run_includes_stdout_in_exception_when_stderr_is_empty(tmp_path, monkeypatch):
    """git_utils.run() must preserve stdout in the exception message.

    git commit writes 'nothing to commit' to stdout, not stderr.  If only
    stderr is included in the exception the caller sees an empty error string.
    """
    # Simulate the exact behaviour of 'git commit' when nothing is staged:
    # exit code 1, useful message on stdout, empty stderr.
    fake_result = subprocess.CompletedProcess(
        args="git commit -m msg",
        returncode=1,
        stdout="On branch main\nno changes added to commit\n",
        stderr="",
    )
    monkeypatch.setattr(
        git_utils.subprocess, "run", lambda *a, **kw: fake_result
    )
    with pytest.raises(Exception) as exc_info:
        git_utils.run("git commit -m msg")
    assert "no changes added to commit" in str(exc_info.value)


def test_git_run_includes_stderr_when_present(tmp_path, monkeypatch):
    """git_utils.run() must still include stderr when it is non-empty."""
    fake_result = subprocess.CompletedProcess(
        args="git push",
        returncode=1,
        stdout="",
        stderr="error: failed to push some refs",
    )
    monkeypatch.setattr(
        git_utils.subprocess, "run", lambda *a, **kw: fake_result
    )
    with pytest.raises(Exception) as exc_info:
        git_utils.run("git push")
    assert "failed to push some refs" in str(exc_info.value)


def test_git_run_includes_both_streams_when_both_present(monkeypatch):
    """When both stdout and stderr carry text both must appear in the exception."""
    fake_result = subprocess.CompletedProcess(
        args="git push",
        returncode=128,
        stdout="hint: some helpful text",
        stderr="fatal: repository not found",
    )
    monkeypatch.setattr(
        git_utils.subprocess, "run", lambda *a, **kw: fake_result
    )
    with pytest.raises(Exception) as exc_info:
        git_utils.run("git push")
    msg = str(exc_info.value)
    assert "fatal: repository not found" in msg
    assert "hint: some helpful text" in msg


def test_requirements_matches_head_true_when_content_identical(tmp_path, monkeypatch):
    """_requirements_matches_head returns True when HEAD:requirements.txt matches."""
    monkeypatch.setattr(
        generate_successes.subprocess if hasattr(generate_successes, "subprocess") else __import__("subprocess"),
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(
            args=a[0], returncode=0, stdout="httpx==0.27.0\n", stderr=""
        ),
    )
    # Patch the internal subprocess call inside _requirements_matches_head
    import unittest.mock as mock
    with mock.patch("subprocess.run", return_value=subprocess.CompletedProcess(
        args=[], returncode=0, stdout="httpx==0.27.0\n", stderr=""
    )):
        assert generate_successes._requirements_matches_head("httpx==0.27.0") is True
        assert generate_successes._requirements_matches_head("requests==2.31.0") is False


def test_ensure_attempt_commit_uses_empty_commit_when_requirements_already_at_head(
    tmp_path, monkeypatch
):
    """When requirements.txt already matches HEAD, create_empty_commit is used.

    This is the scenario that caused attempt 5 to fail: the same dependency
    was already committed at HEAD, so git commit would fail with
    'nothing to commit'.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "requirements.txt").write_text("httpx==0.27.0\n", encoding="utf-8")

    # Simulate: find_commit_by_message returns None (no prior attempt commit)
    monkeypatch.setattr(generate_successes, "find_commit_by_message", lambda msg: None)
    # Simulate: requirements already match HEAD
    monkeypatch.setattr(
        generate_successes, "_requirements_matches_head", lambda dep: True
    )

    empty_sha = "aabbccdd1234"
    create_called = []
    push_called = []

    monkeypatch.setattr(
        generate_successes, "create_empty_commit",
        lambda msg: (create_called.append(msg), empty_sha)[1]
    )
    monkeypatch.setattr(
        generate_successes, "push_commit",
        lambda sha: push_called.append(sha)
    )
    # commit_and_push must NOT be called
    monkeypatch.setattr(
        generate_successes, "commit_and_push",
        lambda msg: (_ for _ in ()).throw(AssertionError("commit_and_push must not be called"))
    )

    pending = {
        "run_number": 3,
        "attempt_number": 5,
        "commit_message": "Success dataset F1 run 0003 attempt 0005: httpx==0.27.0",
        "dependency": "httpx==0.27.0",
        "commit_sha": None,
        "workflow": None,
    }

    sha = generate_successes._ensure_attempt_commit(pending)

    assert sha == empty_sha
    assert pending["commit_sha"] == empty_sha
    assert create_called == ["Success dataset F1 run 0003 attempt 0005: httpx==0.27.0"]
    assert push_called == [empty_sha]


def test_ensure_attempt_commit_uses_commit_and_push_when_requirements_differ(
    tmp_path, monkeypatch
):
    """When requirements.txt differs from HEAD, the normal commit+push path is used."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "requirements.txt").write_text("urllib3==2.2.1\n", encoding="utf-8")

    monkeypatch.setattr(generate_successes, "find_commit_by_message", lambda msg: None)
    # Simulate: requirements do NOT match HEAD (normal new-dependency case)
    monkeypatch.setattr(
        generate_successes, "_requirements_matches_head", lambda dep: False
    )

    normal_sha = "deadbeef9876"
    cap_and_push_called = []

    monkeypatch.setattr(
        generate_successes, "commit_and_push",
        lambda msg: (cap_and_push_called.append(msg), normal_sha)[1]
    )
    monkeypatch.setattr(
        generate_successes, "create_empty_commit",
        lambda msg: (_ for _ in ()).throw(AssertionError("create_empty_commit must not be called"))
    )

    pending = {
        "run_number": 4,
        "attempt_number": 1,
        "commit_message": "Success dataset F1 run 0004 attempt 0001: urllib3==2.2.1",
        "dependency": "urllib3==2.2.1",
        "commit_sha": None,
        "workflow": None,
    }

    sha = generate_successes._ensure_attempt_commit(pending)

    assert sha == normal_sha
    assert cap_and_push_called == ["Success dataset F1 run 0004 attempt 0001: urllib3==2.2.1"]
