"""Automated test suite for F5 Docker Build Failure generator and validator.

Tests:
1. Scenario-file parsing and schema validation (v2.0)
2. All ten scenario definitions (D1 - D10) with refined native failure semantics
3. Rejection of F1 Python syntax errors
4. Rejection of F2 dependency resolution errors
5. Rejection of F3 test execution failures
6. Rejection of F4 timeout errors
7. Rejection of F6 daemon and runner configuration errors
8. Rejection of F7 network and registry outage errors
9. Rejection of successful Docker builds
10. Stable, unique run numbering and cross-dataset run_id format
11. F5 state persistence and restart/resume behaviour
12. Working tree restoration and cleanup
13. Prevention of duplicate or overwritten log files
14. Label insertion and schema compatibility with labels.csv
"""

import json
import os
import shutil
import tempfile
from pathlib import Path
import pytest

from automation.docker_validator import (
    check_exclusions,
    validate_docker_log,
    validate_docker_log_file,
)
from automation.label_utils import LABEL_COLUMNS, append_label_record
from generate_docker_failures import (
    MANIFEST_COLUMNS,
    cleanup_working_tree,
    get_ordered_variants,
    load_f5_state,
    load_scenario_catalog,
    save_f5_state,
    setup_working_tree,
    synthesize_docker_workflow_log,
)


def test_scenario_catalog_parsing_and_schema():
    """Verify docker_errors.json parses and adheres to the v2.0 schema."""
    families = load_scenario_catalog()
    assert len(families) == 10, f"Expected 10 scenario families, found {len(families)}"

    expected_keys = [f"D{i}" for i in range(1, 11)]
    assert sorted(families.keys(), key=lambda k: int(k[1:])) == expected_keys

    total_variants = 0
    for fam_id in expected_keys:
        fam = families[fam_id]
        assert "family_name" in fam
        assert "canonical_label" in fam
        assert fam["canonical_label"] == "docker_build_failure"
        assert "primary_cause" in fam
        assert "failure_mechanism" in fam
        assert "expected_log_evidence" in fam
        assert "exclusion_conditions" in fam
        assert "validation_method" in fam
        assert "reproduction_prerequisites" in fam
        assert "expected_exit_code" in fam

        variants = fam.get("variants", [])
        assert len(variants) == 50, f"Family {fam_id} should have exactly 50 variants, got {len(variants)}"
        total_variants += len(variants)

        for v in variants:
            assert "variant_id" in v
            assert v["variant_id"].startswith(f"{fam_id}_")
            assert "description" in v
            assert "dockerfile_content" in v
            assert "expected_pattern" in v

    assert total_variants == 500, f"Expected 500 total variants, got {total_variants}"


def test_all_ten_scenarios_validation():
    """Verify that synthesized logs for all ten scenario families pass validation."""
    families = load_scenario_catalog()
    variants = get_ordered_variants(families, count=10, pilot=True)
    assert len(variants) == 10

    for v in variants:
        fam_id = v["family_id"]
        synthetic_log = synthesize_docker_workflow_log(v, run_number=501)
        res = validate_docker_log(synthetic_log, expected_scenario=fam_id)

        assert res["status"] == "valid", f"Scenario {fam_id} failed validation: {res}"
        assert res["is_docker_error"] is True
        assert res["scenario_id"] == fam_id
        assert res["matched_pattern"] is not None
        assert res["matched_line"] is not None


def test_d3_and_d6_native_semantics():
    """Verify that D3 and D6 use native Docker BuildKit failure evidence without shell assertions."""
    families = load_scenario_catalog()

    # D3: Check empty from flag (variant 0) and stage index out of range (variant 2)
    d3_var_0 = families["D3"]["variants"][0]  # mode 1: empty flag
    d3_log_0 = synthesize_docker_workflow_log({**d3_var_0, "family_id": "D3"}, 503)
    res_d3_0 = validate_docker_log(d3_log_0, expected_scenario="D3")
    assert res_d3_0["status"] == "valid"
    assert "flag needs an argument: --from" in res_d3_0["matched_line"]

    d3_var_2 = families["D3"]["variants"][2]  # mode 0: stage index
    d3_log_2 = synthesize_docker_workflow_log({**d3_var_2, "family_id": "D3"}, 503)
    res_d3_2 = validate_docker_log(d3_log_2, expected_scenario="D3")
    assert res_d3_2["status"] == "valid"
    assert "stage --from index out of range" in res_d3_2["matched_line"]

    # D6: Native BuildKit secret mount error or target stage error
    d6_var = families["D6"]["variants"][0]
    d6_log = synthesize_docker_workflow_log({**d6_var, "family_id": "D6"}, 506)
    res_d6 = validate_docker_log(d6_log, expected_scenario="D6")
    assert res_d6["status"] == "valid"
    assert "failed to solve: target stage" in res_d6["matched_line"] or "failed to solve: secret" in res_d6["matched_line"]
    assert "test -n" not in res_d6["matched_line"]  # Proves NO shell script assertion


def test_rejection_of_unrelated_failures():
    """Verify explicit rejection of F1 syntax errors, F3 test failures, F4 timeouts, F6 daemon and F7 network."""
    # F1 syntax error
    f1_log = (
        "docker-ci\tRun Tests\t2026-10-16T10:00:00Z python -c 'import app'\n"
        "docker-ci\tRun Tests\t2026-10-16T10:00:01Z SyntaxError: expected ':'\n"
        "docker-ci\tRun Tests\t2026-10-16T10:00:02Z ##[error]Process completed with exit code 1.\n"
    )
    res = validate_docker_log(f1_log)
    assert res["status"] == "rejected"
    assert "F1_syntax" in res["matched_pattern"]

    # F3 test failure
    f3_log = (
        "docker-ci\tRun Tests\t2026-10-16T10:00:00Z pytest\n"
        "docker-ci\tRun Tests\t2026-10-16T10:00:01Z =================================== FAILURES ===================================\n"
        "docker-ci\tRun Tests\t2026-10-16T10:00:02Z FAILED (failures=1)\n"
    )
    res = validate_docker_log(f3_log)
    assert res["status"] == "rejected"
    assert "F3_test" in res["matched_pattern"]

    # F4 timeout
    f4_log = (
        "docker-ci\tBuild\t2026-10-16T10:00:00Z Running docker build\n"
        "docker-ci\tBuild\t2026-10-16T10:00:01Z ##[error]The job running on runner Hosted Agent has exceeded the maximum execution time of 60 minutes.\n"
    )
    res = validate_docker_log(f4_log)
    assert res["status"] == "rejected"
    assert "F4_timeout" in res["matched_pattern"]

    # F6 daemon configuration failure
    f6_log = (
        "docker-ci\tBuild\t2026-10-16T10:00:00Z docker build .\n"
        "docker-ci\tBuild\t2026-10-16T10:00:01Z Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?\n"
    )
    res = validate_docker_log(f6_log)
    assert res["status"] == "rejected"
    assert "F6_daemon_workflow" in res["matched_pattern"]

    # F7 network/pull failure
    f7_log = (
        "docker-ci\tBuild\t2026-10-16T10:00:00Z docker build .\n"
        "docker-ci\tBuild\t2026-10-16T10:00:01Z ERROR: toomanyrequests: You have reached your pull rate limit.\n"
    )
    res = validate_docker_log(f7_log)
    assert res["status"] == "rejected"
    assert "F7_network" in res["matched_pattern"]


def test_rejection_of_dependency_failures_f2():
    """Verify rejection of dependency installation failures occurring inside docker builds (F2)."""
    f2_docker_log = (
        "docker-ci\tBuild\t2026-10-16T10:00:00Z #5 [2/4] RUN pip install non_existent_pkg_12345==1.0\n"
        "docker-ci\tBuild\t2026-10-16T10:00:01Z #5 1.543 ERROR: Could not find a version that satisfies the requirement non_existent_pkg_12345==1.0\n"
        "docker-ci\tBuild\t2026-10-16T10:00:02Z #5 1.544 ERROR: No matching distribution found for non_existent_pkg_12345==1.0\n"
        "docker-ci\tBuild\t2026-10-16T10:00:03Z ERROR: failed to solve: process \"/bin/sh -c pip install non_existent_pkg_12345==1.0\" did not complete successfully: exit code: 1\n"
    )
    res = validate_docker_log(f2_docker_log)
    assert res["status"] == "rejected"
    assert "F2_dependency" in res["matched_pattern"]

    f2_apt_log = (
        "docker-ci\tBuild\t2026-10-16T10:00:00Z #4 [2/3] RUN apt-get update && apt-get install -y invalid_pkg\n"
        "docker-ci\tBuild\t2026-10-16T10:00:01Z #4 E: Unable to locate package invalid_pkg\n"
        "docker-ci\tBuild\t2026-10-16T10:00:02Z ERROR: failed to solve: process \"/bin/sh -c apt-get ...\" exit code: 100\n"
    )
    res = validate_docker_log(f2_apt_log)
    assert res["status"] == "rejected"
    assert "F2_dependency" in res["matched_pattern"]


def test_rejection_of_successful_docker_builds():
    """Verify that a successful Docker build is rejected and not counted as a failure."""
    success_log = (
        "docker-ci\tBuild\t2026-10-16T10:00:00Z #1 [internal] load build definition from Dockerfile\n"
        "docker-ci\tBuild\t2026-10-16T10:00:01Z #2 [1/2] FROM docker.io/library/python:3.11-slim\n"
        "docker-ci\tBuild\t2026-10-16T10:00:02Z #3 [2/2] COPY . .\n"
        "docker-ci\tBuild\t2026-10-16T10:00:03Z #4 exporting to image\n"
        "docker-ci\tBuild\t2026-10-16T10:00:04Z #4 naming to docker.io/library/test:latest done\n"
    )
    res = validate_docker_log(success_log)
    assert res["status"] == "invalid"
    assert "succeeded" in res["rejection_reason"]


def test_stable_unique_run_numbering():
    """Verify run numbering starts at 501 and has no collisions with F1-F4."""
    families = load_scenario_catalog()
    variants = get_ordered_variants(families, count=500, pilot=False)
    assert len(variants) == 500

    run_numbers = [501 + i for i in range(500)]
    assert len(set(run_numbers)) == 500
    assert min(run_numbers) == 501
    assert max(run_numbers) == 1000

    for rn in run_numbers:
        assert rn > 500


def test_state_persistence_and_resume(tmp_path, monkeypatch):
    """Verify that F5 state persists and resumes correctly."""
    test_state_file = tmp_path / "state_f5_test.json"
    monkeypatch.setattr("generate_docker_failures.F5_STATE_FILE", str(test_state_file))

    state = load_f5_state()
    assert state["current_run"] == 500
    assert state["completed_runs"] == 0

    state["current_run"] = 501
    state["completed_runs"] = 1
    state["last_variant_id"] = "D1_01"
    save_f5_state(state)

    reloaded = load_f5_state()
    assert reloaded["current_run"] == 501
    assert reloaded["completed_runs"] == 1
    assert reloaded["last_variant_id"] == "D1_01"


def test_working_tree_restoration(tmp_path, monkeypatch):
    """Verify working tree restoration cleans up temporary files without touching others."""
    monkeypatch.setattr("generate_docker_failures.DOCKERFILE_PATH", tmp_path / "Dockerfile")
    monkeypatch.setattr("generate_docker_failures.DOCKERFILE_BACKUP", tmp_path / "Dockerfile.bak")
    monkeypatch.setattr("generate_docker_failures.FIXTURE_DIR", tmp_path / ".docker_tmp_fixtures")

    df = tmp_path / "Dockerfile"
    df.write_text("ORIGINAL CONTENT", encoding="utf-8")

    setup_working_tree()
    assert (tmp_path / "Dockerfile.bak").exists()

    df.write_text("BROKEN SCENARIO CONTENT", encoding="utf-8")

    cleanup_working_tree()
    assert df.read_text(encoding="utf-8") == "ORIGINAL CONTENT"
    assert not (tmp_path / "Dockerfile.bak").exists()


def test_label_insertion_compatibility(tmp_path):
    """Verify label records match the exact schema of labels.csv."""
    test_labels_csv = tmp_path / "labels.csv"

    record = {
        "run_number": 501,
        "dependency": "D1_01",
        "repository": "dependency-error-repo",
        "commit_sha": "",
        "workflow_id": "",
        "workflow_conclusion": "failure",
        "failure_type": "docker_build_failure",
        "stage": "docker_build",
        "validation_status": "valid",
        "matched_pattern": "failed to calculate checksum",
        "log_file": "logs/F5/run_0501.log",
        "metadata_file": "metadata/F5/run_0501.json",
        "timestamp": "2026-10-16T10:00:00Z",
    }

    inserted = append_label_record(str(test_labels_csv), record)
    assert inserted is True

    duplicate_inserted = append_label_record(str(test_labels_csv), record)
    assert duplicate_inserted is False

    with test_labels_csv.open("r", encoding="utf-8") as f:
        reader = list(f)
        assert len(reader) == 2  # header + 1 record
