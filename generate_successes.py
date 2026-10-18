"""Generate successful GitHub Actions dependency-installation logs.

Each run writes one valid package spec from success_dependencies.txt as the
sole content of requirements.txt, commits and pushes the change, waits for
the workflow to complete with conclusion "success", downloads the log,
validates that the selected dependency was installed successfully, and records
metadata + CSV.

The CI workflow installs the selected dependency from requirements.txt.
No test suite or compilation step is required.

Approach mirrors the former failure generator but only accepts runs whose
workflow conclusion is "success" and whose log confirms the installation.
"""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess

from automation.git_utils import (
    commit_and_push,
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

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

METADATA_KEYS = (
    "run_id",
    "outcome",
    "category_id",
    "failure_type",
    "success_family",
    "dependency",
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

SUCCESS_DEPENDENCIES_FILE = "success_dependencies.txt"

# Files that must be clean (committed, no pending changes) before collection
# starts. requirements.txt is included because it is the file we modify each
# run — it must start from a committed baseline.
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
    "success_dependencies.txt",
    "test_successes.py",
    "test_workflow.py",
)

# ---------------------------------------------------------------------------
# Dependency helpers
# ---------------------------------------------------------------------------

def load_success_dependencies(path=SUCCESS_DEPENDENCIES_FILE):
    """Return the list of valid package specs from *path*.

    Blank lines and lines beginning with ``#`` are ignored.

    Args:
        path: Path to the dependency list file.

    Returns:
        list[str]: Non-empty, non-comment lines stripped of whitespace.

    Raises:
        FileNotFoundError: If *path* does not exist.
        ValueError: If the file contains no usable entries.
    """
    entries = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                entries.append(stripped)
    if not entries:
        raise ValueError(
            f"{path} contains no usable dependency entries. "
            "Add at least one non-comment, non-blank line."
        )
    return entries


def update_requirements(dependency):
    """Write *dependency* as the sole content of requirements.txt.

    The file contains exactly one non-blank line: the selected package
    specifier.  The CI workflow installs it directly; no other packages
    are written here.

    Args:
        dependency: A valid pip requirement specifier, e.g. ``requests==2.31.0``.
    """
    with open("requirements.txt", "w", encoding="utf-8") as fh:
        fh.write(f"{dependency}\n")

# ---------------------------------------------------------------------------
# Timestamp
# ---------------------------------------------------------------------------

def _utc_timestamp():
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )

# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

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
            "The following tracked files have uncommitted changes. "
            "Commit them before starting collection:\n"
            + result.stdout.strip()
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

# ---------------------------------------------------------------------------
# Metadata / CSV helpers
# ---------------------------------------------------------------------------

def _make_metadata(run_number, workflow, commit_sha, log_path, validation_notes, dependency):
    """Build and return the 17-key success metadata dict.

    Args:
        run_number: Dataset-sequential run number (int).
        workflow: Completed workflow record dict from wait_for_run().
        commit_sha: The exact commit SHA that triggered the workflow.
        log_path: Relative POSIX path to the saved log file.
        validation_notes: Human-readable string from validate_success_workflow_log().
        dependency: The pip requirement specifier that was installed,
            e.g. ``"requests==2.31.0"``.

    Returns:
        dict: Metadata with keys matching METADATA_KEYS exactly.

    Raises:
        ValueError: If the workflow does not match the expected commit or outcome.
    """
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
        "dependency": dependency,
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
    with path.open("r", encoding="utf-8") as fh:
        existing = json.load(fh)
    if tuple(existing) != METADATA_KEYS:
        raise ValueError(f"Existing success metadata has an invalid schema: {path}")
    for key in METADATA_KEYS:
        if key != "timestamp" and existing[key] != expected[key]:
            raise ValueError(f"Existing success metadata does not match this run: {path}")
    return existing


def _csv_record(run_number, dependency, metadata, matched_line):
    """Build the 13-column CSV row for one accepted success run.

    Args:
        run_number: Dataset-sequential run number (int).
        dependency: The package specifier that was installed, e.g. ``requests==2.31.0``.
        metadata: The accepted metadata dict for this run.
        matched_line: The actual pip log line that confirmed installation, e.g.
            ``"Successfully installed requests-2.31.0 urllib3-2.8.0"``.

    Returns:
        dict: Keys matching LABEL_COLUMNS in the correct order.
    """
    return {
        "run_number": run_number,
        "dependency": dependency,
        "repository": REPO_NAME,
        "commit_sha": metadata["commit_sha"],
        "workflow_id": metadata["workflow_id"],
        "workflow_conclusion": "success",
        "failure_type": "",
        "stage": "build",
        "validation_status": "valid",
        "matched_pattern": matched_line or "",
        "log_file": metadata["log_file"],
        "metadata_file": f"{SUCCESS_METADATA_FOLDER}/run_{run_number:04d}.json",
        "timestamp": metadata["timestamp"],
    }


def _existing_csv_record(run_number):
    with open(SUCCESS_CSV_FILE, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("run_number") == str(run_number):
                return row
    return None


def _persist_csv_record(run_number, dependency, metadata, matched_line):
    record = _csv_record(run_number, dependency, metadata, matched_line)
    inserted = append_label_record(SUCCESS_CSV_FILE, record)
    if not inserted:
        existing = _existing_csv_record(run_number)
        expected = {key: str(record.get(key, "")) for key in LABEL_COLUMNS}
        if existing != expected:
            raise ValueError(
                f"Existing success CSV row does not match run {run_number}."
            )

# ---------------------------------------------------------------------------
# Commit helpers
# ---------------------------------------------------------------------------

def _next_pending_attempt(state, dependencies):
    """Create the next pending-attempt entry and save state.

    The dependency is chosen by ``accepted_count`` so every accepted sample
    maps to a unique entry in the dependency list. Retries of the same sample
    reuse the same dependency (stored in ``pending``).

    Args:
        state: Mutable state dict.
        dependencies: Full list of dependency strings loaded at startup.
    """
    run_number = state["accepted_count"] + 1
    attempt_number = state["attempt_count"] + 1
    dependency = dependencies[state["accepted_count"]]
    commit_message = (
        f"Success dataset {SUCCESS_FAMILY} run {run_number:04d} "
        f"attempt {attempt_number:04d}: {dependency}"
    )
    state["attempt_count"] = attempt_number
    state["pending"] = {
        "run_number": run_number,
        "attempt_number": attempt_number,
        "commit_message": commit_message,
        "dependency": dependency,
        "commit_sha": None,
        "workflow": None,
    }
    _save_success_state(state)


def _requirements_matches_head(dependency):
    """Return True if requirements.txt at HEAD already contains exactly *dependency*.

    When this is the case, ``git add . && git commit`` would produce a
    "nothing to commit" error because the working-tree file is identical to
    the committed file.  The caller should use an empty commit instead.

    Args:
        dependency: The pip requirement specifier, e.g. ``"httpx==0.27.0"``.

    Returns:
        bool: True if HEAD:requirements.txt is already ``dependency\\n``.
    """
    import subprocess as _subprocess
    result = _subprocess.run(
        ["git", "show", "HEAD:requirements.txt"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        # No HEAD yet (initial repo state) — treat as not matching.
        return False
    return result.stdout.strip() == dependency.strip()


def _ensure_attempt_commit(pending):
    """Ensure a unique commit for this attempt is created and pushed.

    On crash-resume, the commit may already exist locally (found via message
    search); we reuse it rather than creating a duplicate.

    When a new commit is needed, we first write *dependency* into
    requirements.txt and try ``commit_and_push``.  If the file is already
    identical to HEAD (which happens on retries where the previous attempt
    committed the same dependency), ``git commit`` would fail with "nothing to
    commit".  In that case we fall back to ``create_empty_commit`` + ``push_commit``
    which produces a genuine new commit SHA without touching any file — enough to
    trigger a new GitHub Actions run.

    Args:
        pending: The pending-attempt dict from state.

    Returns:
        str: The commit SHA for this attempt.
    """
    commit_sha = pending.get("commit_sha")
    if commit_sha is None:
        # Check whether a prior interrupted run already created this commit.
        commit_sha = find_commit_by_message(pending["commit_message"])

    if commit_sha is None:
        dependency = pending["dependency"]
        update_requirements(dependency)

        if _requirements_matches_head(dependency):
            # requirements.txt is already at HEAD with the same content — a
            # normal commit would fail with "nothing to commit".  Use an empty
            # commit so this attempt gets a unique SHA and triggers CI.
            commit_sha = create_empty_commit(pending["commit_message"])
            push_commit(commit_sha)
        else:
            commit_sha = commit_and_push(pending["commit_message"])

    pending["commit_sha"] = commit_sha
    return commit_sha

# ---------------------------------------------------------------------------
# Log helpers
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Per-run processing
# ---------------------------------------------------------------------------

def _process_successful_workflow(state, pending, workflow, commit_sha):
    """Validate, persist, and record one completed workflow attempt.

    Args:
        state: Mutable state dict.
        pending: The pending-attempt dict from state.
        workflow: Completed workflow record returned by wait_for_run().
        commit_sha: The commit SHA for this attempt.

    Returns:
        bool: True if the workflow was accepted as a valid success sample,
              False if its conclusion was not "success".

    Raises:
        ValueError: If SHA mismatch, or the log fails validation.
    """
    run_number = pending["run_number"]
    dependency = pending["dependency"]

    if workflow.get("headSha") != commit_sha:
        raise ValueError("Workflow SHA does not match the success attempt commit.")
    if workflow.get("status") != "completed" or workflow.get("conclusion") != "success":
        return False

    pending["workflow"] = workflow
    pending["commit_sha"] = commit_sha
    _save_success_state(state)

    log_text = _load_or_download_log(workflow, run_number)
    validation = validate_success_workflow_log(log_text, dependency=dependency)
    if validation["status"] != "valid":
        raise ValueError(
            "Successful workflow log did not confirm dependency installation."
        )

    log_path = (Path(SUCCESS_LOG_FOLDER) / f"run_{run_number:04d}.log").as_posix()
    metadata = _make_metadata(
        run_number,
        workflow,
        commit_sha,
        log_path,
        validation["validation_notes"],
        dependency,
    )
    metadata_path = Path(SUCCESS_METADATA_FOLDER) / f"run_{run_number:04d}.json"
    if metadata_path.exists():
        metadata = _validate_existing_metadata(metadata_path, metadata)
    else:
        save_metadata(str(metadata_path), metadata)

    _persist_csv_record(run_number, dependency, metadata, validation["matched_line"])

    state["accepted_count"] += 1
    state["pending"] = None
    _save_success_state(state)
    return True

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    _require_generation_files_committed()

    dependencies = load_success_dependencies()
    if len(dependencies) < SUCCESS_TOTAL_RUNS:
        raise ValueError(
            f"success_dependencies.txt has only {len(dependencies)} entries but "
            f"{SUCCESS_TOTAL_RUNS} are required. Add more entries and re-run."
        )

    ensure_label_file(SUCCESS_CSV_FILE)
    state = _load_success_state()
    attempts_for_sample = 0

    while state["accepted_count"] < SUCCESS_TOTAL_RUNS:
        if state["pending"] is None:
            attempts_for_sample = 0
            _next_pending_attempt(state, dependencies)

        pending = state["pending"]
        attempts_for_sample += 1

        print(
            f"\n[Run {pending['run_number']}/{SUCCESS_TOTAL_RUNS}] "
            f"attempt {pending['attempt_number']} — {pending['dependency']}"
        )

        try:
            commit_sha = _ensure_attempt_commit(pending)
            _save_success_state(state)
            print(f"Commit SHA: {commit_sha}")
        except Exception as exc:
            print(f"Commit/push failed: {exc}")
            raise

        workflow = pending.get("workflow")
        if workflow is None:
            workflow = wait_for_run(commit_sha)

        if workflow.get("headSha") != commit_sha:
            raise ValueError(
                f"Workflow lookup returned a mismatched SHA for attempt {commit_sha}."
            )
        if workflow.get("status") != "completed":
            raise ValueError("Workflow lookup returned an incomplete workflow.")

        accepted = _process_successful_workflow(state, pending, workflow, commit_sha)

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
                    "workflow attempts for one success sample. "
                    f"Dependency: {pending['dependency']}"
                )
            continue

        print(
            f"Accepted success sample {state['accepted_count']} "
            f"of {SUCCESS_TOTAL_RUNS}."
        )
        attempts_for_sample = 0

    print("\nSuccessful workflow log generation complete.")


if __name__ == "__main__":
    main()
