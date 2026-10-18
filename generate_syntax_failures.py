"""F1 Syntax Error dataset generator.

This script is the F1 counterpart to generate_failures.py (F2 dependency errors).
It follows the identical overall flow:

    select scenario
    → write fresh broken app.py
    → git commit/push
    → wait for matching GitHub Actions run
    → download actual workflow log
    → validate log for genuine SyntaxError/IndentationError/TabError
    → save log
    → save metadata
    → append label to labels.csv
    → advance state_f1.json

State is only advanced AFTER every downstream step succeeds.
If log collection or validation fails the run is aborted and state is NOT advanced.

Key design decisions
--------------------
- Each run writes a COMPLETE, FRESH app.py from the scenario definition.
  This makes every run independent.  There is no risk of Run N modifying
  an already-broken file left by Run N-1.
- The original app.py is backed up at startup and restored after every run
  so the working tree is never left in a confusing state.
- All shared automation helpers (git_utils, workflow_utils, log_utils,
  metadata_utils, label_utils, state_utils) are reused without modification.
- F2 infrastructure (generate_failures.py, state.json, logs/F2, metadata/F2)
  is completely untouched.
"""

import json
import os
import shutil
import traceback
from datetime import datetime, timezone
from pathlib import Path

from automation.git_utils import commit_and_push
from automation.label_utils import append_label_record
from automation.log_utils import download_workflow_log
from automation.metadata_utils import save_metadata
from automation.state_utils import save_state  # load_state unused; F1 uses _load_json
from automation.syntax_validator import validate_syntax_log_file
from automation.workflow_utils import wait_for_run

from config import (
    F1_FAILURE_TYPE,
    F1_LOG_FOLDER,
    F1_METADATA_FOLDER,
    F1_STAGE,
    F1_STATE_FILE,
    F1_TOTAL_RUNS,
    REPO_NAME,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
APP_PY = Path("app.py")
APP_PY_BACKUP = Path("app.py.bak")
SYNTAX_ERRORS_FILE = Path("syntax_errors.txt")


# ---------------------------------------------------------------------------
# Scenario loading
# ---------------------------------------------------------------------------

def load_scenarios():
    """Parse syntax_errors.txt and return a list of scenario dicts.

    Each non-blank, non-comment line must follow the format:
        scenario_id|description|broken_app_py_content

    The content field uses \\n as a literal newline placeholder.

    Returns:
        list[dict]: Each dict has keys: id, description, content.

    Raises:
        ValueError: If the file is empty or any line is malformed.
    """
    if not SYNTAX_ERRORS_FILE.exists():
        raise FileNotFoundError(f"{SYNTAX_ERRORS_FILE} not found.")

    scenarios = []
    with SYNTAX_ERRORS_FILE.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|", 2)
            if len(parts) != 3:
                raise ValueError(
                    f"Malformed line in {SYNTAX_ERRORS_FILE}: {line!r}\n"
                    "Expected format: scenario_id|description|content"
                )
            scenario_id, description, content_escaped = parts
            content = content_escaped.replace("\\n", "\n").replace("\\t", "\t")
            scenarios.append({
                "id": scenario_id.strip(),
                "description": description.strip(),
                "content": content,
            })

    if not scenarios:
        raise ValueError(f"{SYNTAX_ERRORS_FILE} contains no valid scenarios.")

    return scenarios


# ---------------------------------------------------------------------------
# app.py helpers
# ---------------------------------------------------------------------------

def backup_app_py():
    """Copy app.py to app.py.bak if no backup already exists."""
    if not APP_PY_BACKUP.exists():
        shutil.copy2(APP_PY, APP_PY_BACKUP)
        print(f"Backed up {APP_PY} → {APP_PY_BACKUP}")


def restore_app_py():
    """Restore app.py from app.py.bak."""
    if APP_PY_BACKUP.exists():
        shutil.copy2(APP_PY_BACKUP, APP_PY)
        print(f"Restored {APP_PY} from {APP_PY_BACKUP}")
    else:
        # Fallback: write a minimal valid app.py so the repo is not broken
        APP_PY.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        print(f"No backup found — wrote minimal valid {APP_PY}")


def write_broken_app_py(scenario):
    """Overwrite app.py with the broken content from the scenario.

    This is always a FRESH write of a COMPLETE file, never a delta on
    whatever was previously in app.py.  This guarantees independence
    between runs.

    Args:
        scenario (dict): Scenario dict with 'content' key.
    """
    APP_PY.write_text(scenario["content"], encoding="utf-8")
    print(f"Wrote broken app.py for scenario: {scenario['id']}")


# ---------------------------------------------------------------------------
# State helpers (F1-specific file)
# ---------------------------------------------------------------------------

def load_f1_state():
    """Load state_f1.json, creating it with default values if absent."""
    if not Path(F1_STATE_FILE).exists():
        default = {"current_run": 0, "last_syntax_error_type": None}
        with open(F1_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=4)
        return default
    return _load_json(F1_STATE_FILE)


def save_f1_state(state):
    """Persist state to state_f1.json."""
    with open(F1_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=4)


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def main():
    scenarios = load_scenarios()

    state = _load_json(F1_STATE_FILE) if Path(F1_STATE_FILE).exists() else {"current_run": 0, "last_syntax_error_type": None}

    if not scenarios:
        raise ValueError("No scenarios available.")

    # Scenarios are intentionally cycled using modulo so we can generate a
    # dataset larger than the number of unique scenario templates while
    # retaining controlled, reproducible failure categories.  Run numbering
    # and output file numbering (run_0001, run_0002, …) remain strictly
    # sequential and are never reset when the scenario list wraps around.
    n_scenarios = len(scenarios)

    # Back up the original app.py once at the start of the session.
    backup_app_py()

    while state["current_run"] < F1_TOTAL_RUNS:
        current = state["current_run"]
        scenario = scenarios[current % n_scenarios]

        print()
        print(f"{'='*60}")
        print(f"Run {current + 1} / {F1_TOTAL_RUNS}")
        print(f"Scenario: {scenario['id']} — {scenario['description']}")
        print(f"{'='*60}")

        try:
            # ------------------------------------------------------------------
            # 1. Write a fresh, complete, broken app.py for this scenario.
            #    This is always a full overwrite, not a modification of the
            #    previous run's broken file.
            # ------------------------------------------------------------------
            write_broken_app_py(scenario)

            # ------------------------------------------------------------------
            # 2. Commit and push.
            # ------------------------------------------------------------------
            sha = commit_and_push(f"Syntax Error Run {current + 1} [{scenario['id']}]")
            print(f"Commit SHA: {sha}")

            # ------------------------------------------------------------------
            # 3. Wait for the matching GitHub Actions run to complete.
            # ------------------------------------------------------------------
            workflow = wait_for_run(sha)
            print(f"Workflow completed: {workflow['databaseId']}")

            # ------------------------------------------------------------------
            # 4. Download the actual workflow log.
            # ------------------------------------------------------------------
            log_path = download_workflow_log(workflow, current + 1, log_dir=F1_LOG_FOLDER)
            print(f"Downloaded log: {log_path}")

            # ------------------------------------------------------------------
            # 5. Validate the log for genuine syntax-error patterns.
            # ------------------------------------------------------------------
            validation = validate_syntax_log_file(log_path)
            print(f"Validation status: {validation['status']}")
            print(f"Is syntax error:   {validation['is_syntax_error']}")

            if validation["matched_pattern"] is not None:
                print(f"Matched pattern: {validation['matched_pattern']}")
            if validation["matched_line"] is not None:
                print(f"Matched line:    {validation['matched_line']}")

            if validation["status"] != "valid":
                if validation["status"] == "error":
                    print(f"Validation error: log file could not be read: {log_path}")
                else:
                    print(
                        f"Validation failed: log does not contain a known "
                        f"syntax-error pattern: {log_path}"
                    )
                print("State NOT advanced — run did not pass validation.")
                return

            # ------------------------------------------------------------------
            # 6. Save metadata.
            # ------------------------------------------------------------------
            metadata = {
                "run_number": current + 1,
                "failure_type": F1_FAILURE_TYPE,
                "stage": F1_STAGE,
                "repository": REPO_NAME,
                "commit_sha": sha,
                "workflow_id": workflow["databaseId"],
                "workflow_status": workflow["status"],
                "workflow_conclusion": workflow.get("conclusion"),
                "log_file": log_path,
                "validation_status": validation["status"],
                "is_syntax_error": validation["is_syntax_error"],
                "matched_pattern": validation["matched_pattern"],
                "matched_line": validation["matched_line"],
                "syntax_error_type": scenario["id"],
                "scenario_description": scenario["description"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            metadata_path = f"{F1_METADATA_FOLDER}/run_{(current + 1):04d}.json"

            try:
                save_metadata(metadata_path, metadata)
                print(f"Saved metadata: {metadata_path}")
            except Exception as metadata_exc:
                print(f"Metadata write failed for run {current + 1}: {metadata_exc}")
                print("State NOT advanced — metadata persistence failed.")
                return

            # ------------------------------------------------------------------
            # 7. Append label record to labels.csv.
            #    The existing CSV schema is preserved exactly.
            #    The 'dependency' column holds the scenario id (the "input" for
            #    the run) so the schema stays compatible with F0/F2/F3/F4.
            # ------------------------------------------------------------------
            label_record = {
                "run_number": current + 1,
                "dependency": scenario["id"],          # scenario id in dependency column
                "repository": REPO_NAME,
                "commit_sha": sha,
                "workflow_id": workflow["databaseId"],
                "workflow_conclusion": workflow.get("conclusion"),
                "failure_type": F1_FAILURE_TYPE,
                "stage": F1_STAGE,
                "validation_status": validation["status"],
                "matched_pattern": validation["matched_pattern"],
                "log_file": log_path,
                "metadata_file": metadata_path,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            try:
                inserted = append_label_record("labels.csv", label_record)
                if inserted:
                    print(f"Appended label row for run {current + 1} to labels.csv")
                else:
                    print(f"Label row for run {current + 1} already exists in labels.csv")
            except Exception as label_exc:
                print(f"Label write failed for run {current + 1}: {label_exc}")
                print("State NOT advanced — label persistence failed.")
                return

            # ------------------------------------------------------------------
            # 8. Restore app.py to its original valid state BEFORE advancing
            #    state, so the working tree is clean for the next run.
            # ------------------------------------------------------------------
            restore_app_py()

            # ------------------------------------------------------------------
            # 9. Advance state only after every step above has succeeded.
            # ------------------------------------------------------------------
            state["current_run"] += 1
            state["last_syntax_error_type"] = scenario["id"]
            save_f1_state(state)

            print(f"Run {current + 1} completed successfully.")

        except KeyboardInterrupt:
            print("\nGenerator interrupted by user.")
            restore_app_py()
            return

        except Exception as exc:
            print(f"Run {current + 1} failed.")
            print(f"Reason: {exc}")
            print()
            print("--- Full traceback ---")
            traceback.print_exc()
            restore_app_py()
            return

    print()
    print("F1 dataset generation complete.")
    print(f"Total runs completed: {state['current_run']}")


if __name__ == "__main__":
    main()
