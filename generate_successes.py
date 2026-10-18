import csv
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess

from automation.git_utils import (
    create_empty_commit,
    find_commit_by_message,
    push_commit,
)
from automation.label_utils import LABEL_COLUMNS, append_label_record, ensure_label_file
from automation.log_utils import download_workflow_log
from automation.metadata_utils import save_metadata
from automation.state_utils import load_state, save_state
from automation.validator import validate_success_workflow_log
from automation.workflow_utils import wait_for_run
from config import (
    REPO_NAME,
    SUCCESS_CSV_FILE,
    SUCCESS_FAMILY,
    SUCCESS_LOG_FOLDER,
    SUCCESS_MAX_ATTEMPTS_PER_SAMPLE,
    SUCCESS_METADATA_FOLDER,
    SUCCESS_SCENARIO,
    SUCCESS_STATE_FILE,
    SUCCESS_TOTAL_RUNS,
)


METADATA_KEYS = (
    "run_id",
    "outcome",
    "category_id",
    "failure_type",
    "success_family",
    "scenario_id",
    "log_file",
    "generation_method",
    "actual_execution_validated",
    "workflow_id",
    "commit_sha",
    "workflow_status",
    "workflow_conclusion",
    "validation_status",
    "validation_notes",
    "timestamp",
)

GENERATION_FILES = (
    ".github/workflows/ci.yml",
    ".gitignore",
    "automation/git_utils.py",
    "automation/label_utils.py",
    "automation/state_utils.py",
    "automation/validator.py",
    "config.py",
    "generate_successes.py",
    "requirements.txt",
    "test_successes.py",
    "test_workflow.py",
)


def _utc_timestamp():
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _initial_state():
    return {"accepted_count": 0, "attempt_count": 0, "pending": None}


def _require_generation_files_committed():
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", *GENERATION_FILES],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    if result.stdout.strip():
        raise RuntimeError(
            "Commit the success generator and CI workflow changes before starting "
            "collection. No files were staged or committed."
        )


def _load_success_state():
    state_path = Path(SUCCESS_STATE_FILE)
    if not state_path.exists():
        state = _initial_state()
        save_state(state, SUCCESS_STATE_FILE)
        return state

    state = load_state(SUCCESS_STATE_FILE)
    if (
        not isinstance(state, dict)
        or not isinstance(state.get("accepted_count"), int)
        or not isinstance(state.get("attempt_count"), int)
        or "pending" not in state
    ):
        raise ValueError(f"Invalid success state file: {SUCCESS_STATE_FILE}")
    return state


def _save_success_state(state):
    save_state(state, SUCCESS_STATE_FILE)


def _make_metadata(run_number, workflow, commit_sha, log_path, validation_notes):
    if (
        workflow.get("headSha") != commit_sha
        or workflow.get("status") != "completed"
        or workflow.get("conclusion") != "success"
    ):
        raise ValueError("Metadata requires a successful workflow for the exact commit.")

    metadata = {
        "run_id": f"S_{SUCCESS_FAMILY}_run_{run_number:04d}",
        "outcome": "success",
        "category_id": None,
        "failure_type": None,
        "success_family": SUCCESS_FAMILY,
        "scenario_id": SUCCESS_SCENARIO,
        "log_file": log_path,
        "generation_method": "live_workflow",
        "actual_execution_validated": True,
        "workflow_id": int(workflow["databaseId"]),
        "commit_sha": commit_sha,
        "workflow_status": "completed",
        "workflow_conclusion": "success",
        "validation_status": "valid",
        "validation_notes": validation_notes,
        "timestamp": _utc_timestamp(),
    }
    if tuple(metadata) != METADATA_KEYS:
        raise AssertionError("Success metadata keys do not match the required schema.")
    return metadata


def _validate_existing_metadata(path, expected):
    with path.open("r", encoding="utf-8") as metadata_file:
        existing = json.load(metadata_file)
    if tuple(existing) != METADATA_KEYS:
        raise ValueError(f"Existing success metadata has an invalid schema: {path}")
    for key in METADATA_KEYS:
        if key != "timestamp" and existing[key] != expected[key]:
            raise ValueError(f"Existing success metadata does not match this run: {path}")
    return existing


def _csv_record(run_number, metadata):
    return {
        "run_number": run_number,
        "dependency": "",
        "repository": REPO_NAME,
        "commit_sha": metadata["commit_sha"],
        "workflow_id": metadata["workflow_id"],
        "workflow_conclusion": "success",
        "failure_type": "",
        "stage": "ci",
        "validation_status": "valid",
        "matched_pattern": "",
        "log_file": metadata["log_file"],
        "metadata_file": f"{SUCCESS_METADATA_FOLDER}/run_{run_number:04d}.json",
        "timestamp": metadata["timestamp"],
    }


def _existing_csv_record(run_number):
    with open(SUCCESS_CSV_FILE, newline="", encoding="utf-8") as csv_file:
        for row in csv.DictReader(csv_file):
            if row.get("run_number") == str(run_number):
                return row
    return None


def _persist_csv_record(run_number, metadata):
    record = _csv_record(run_number, metadata)
    inserted = append_label_record(SUCCESS_CSV_FILE, record)
    if not inserted:
        existing = _existing_csv_record(run_number)
        expected = {key: str(record.get(key, "")) for key in LABEL_COLUMNS}
        if existing != expected:
            raise ValueError(
                f"Existing success CSV row does not match run {run_number}."
            )


def _next_pending_attempt(state):
    run_number = state["accepted_count"] + 1
    attempt_number = state["attempt_count"] + 1
    commit_message = (
        f"Success dataset {SUCCESS_FAMILY} run {run_number:04d} "
        f"attempt {attempt_number:04d}"
    )
    state["attempt_count"] = attempt_number
    state["pending"] = {
        "run_number": run_number,
        "attempt_number": attempt_number,
        "commit_message": commit_message,
        "commit_sha": None,
        "workflow": None,
    }
    _save_success_state(state)


def _ensure_attempt_commit(pending):
    commit_sha = pending.get("commit_sha")
    if commit_sha is None:
        commit_sha = find_commit_by_message(pending["commit_message"])
        if commit_sha is None:
            commit_sha = create_empty_commit(pending["commit_message"])
        pending["commit_sha"] = commit_sha
    push_commit(commit_sha)
    return commit_sha


def _load_or_download_log(workflow, run_number):
    destination = Path(SUCCESS_LOG_FOLDER) / f"run_{run_number:04d}.log"
    if destination.exists():
        if destination.stat().st_size == 0:
            raise ValueError(f"Existing success log is empty: {destination}")
        return destination.read_text(encoding="utf-8", errors="replace")

    downloaded_path = download_workflow_log(
        workflow,
        run_number,
        log_dir=SUCCESS_LOG_FOLDER,
    )
    downloaded = Path(downloaded_path)
    if not downloaded.exists() or downloaded.stat().st_size == 0:
        raise ValueError(f"Downloaded success log is missing or empty: {downloaded}")
    return downloaded.read_text(encoding="utf-8", errors="replace")


def _process_successful_workflow(state, pending, workflow, commit_sha):
    run_number = pending["run_number"]
    if workflow.get("headSha") != commit_sha:
        raise ValueError("Workflow SHA does not match the success attempt commit.")
    if workflow.get("status") != "completed" or workflow.get("conclusion") != "success":
        return False

    pending["workflow"] = workflow
    pending["commit_sha"] = commit_sha
    _save_success_state(state)

    log_text = _load_or_download_log(workflow, run_number)
    validation = validate_success_workflow_log(log_text)
    if validation["status"] != "valid":
        raise ValueError(
            "Successful workflow log did not confirm Python compilation and test results."
        )

    log_path = (Path(SUCCESS_LOG_FOLDER) / f"run_{run_number:04d}.log").as_posix()
    metadata = _make_metadata(
        run_number,
        workflow,
        commit_sha,
        log_path,
        validation["validation_notes"],
    )
    metadata_path = Path(SUCCESS_METADATA_FOLDER) / f"run_{run_number:04d}.json"
    if metadata_path.exists():
        metadata = _validate_existing_metadata(metadata_path, metadata)
    else:
        save_metadata(str(metadata_path), metadata)

    _persist_csv_record(run_number, metadata)

    state["accepted_count"] += 1
    state["pending"] = None
    _save_success_state(state)
    return True


def main():
    _require_generation_files_committed()
    ensure_label_file(SUCCESS_CSV_FILE)
    state = _load_success_state()
    attempts_for_sample = 0

    while state["accepted_count"] < SUCCESS_TOTAL_RUNS:
        if state["pending"] is None:
            attempts_for_sample = 0
            _next_pending_attempt(state)
        pending = state["pending"]
        attempts_for_sample += 1
        commit_sha = _ensure_attempt_commit(pending)
        _save_success_state(state)

        workflow = pending.get("workflow")
        if workflow is None:
            workflow = wait_for_run(commit_sha)

        if workflow.get("headSha") != commit_sha:
            raise ValueError(
                f"Workflow lookup returned a mismatched SHA for attempt {commit_sha}."
            )
        if workflow.get("status") != "completed":
            raise ValueError("Workflow lookup returned an incomplete workflow.")

        accepted = _process_successful_workflow(
            state,
            pending,
            workflow,
            commit_sha,
        )
        if not accepted:
            failed_attempt_number = pending["attempt_number"]
            state["pending"] = None
            _save_success_state(state)
            print(
                f"Attempt {failed_attempt_number} did not succeed "
                f"(conclusion: {workflow.get('conclusion')}); it will not count."
            )
            if attempts_for_sample >= SUCCESS_MAX_ATTEMPTS_PER_SAMPLE:
                raise RuntimeError(
                    f"Stopped after {SUCCESS_MAX_ATTEMPTS_PER_SAMPLE} unsuccessful "
                    "workflow attempts for one success sample."
                )
            continue

        print(
            f"Accepted success sample {state['accepted_count']} "
            f"of {SUCCESS_TOTAL_RUNS}."
        )
        attempts_for_sample = 0

    print("Successful workflow log generation complete.")


if __name__ == "__main__":
    main()
