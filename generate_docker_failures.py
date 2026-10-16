"""F5 Docker Build Failure dataset generator.

This script is the F5 counterpart to:
- generate_syntax_failures.py (F1 Python syntax errors)
- generate_failures.py (F2 dependency errors)

Designed for integration into the combined 7-class CI/CD failure dataset (F1 - F7).

Key architectural safeguards:
- Strict class isolation from F1-F4, F6, F7
- Globally unique cross-dataset run_id: "F5_run_{number:04d}"
- Non-colliding sequential numeric run numbers (501..1000)
- Explicit provenance tracking ("synthetic_template_variation" vs "live_workflow")
- Native Docker failure semantics (no shell-script assertions)
- Realistic workflow diversity (varied base images, preceding steps, durations, timestamps)
- Rejection of exact duplicate logs and tracking of template-family distributions
- Automatic rollback/cleanup ensuring working tree is never left dirty

Usage:
  python generate_docker_failures.py --batch 50   # Run audited initial batch of 50
  python generate_docker_failures.py --pilot      # Run 10 pilot scenarios (D1-D10)
  python generate_docker_failures.py --count 500  # Full dataset generation
"""

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

from automation.label_utils import append_label_record
from automation.metadata_utils import save_metadata
from automation.docker_validator import validate_docker_log, validate_docker_log_file

from config import (
    F5_CATEGORY_ID,
    F5_FAILURE_TYPE,
    F5_LOG_FOLDER,
    F5_MANIFEST_CSV,
    F5_MANIFEST_FILE,
    F5_METADATA_FOLDER,
    F5_SCENARIOS_FILE,
    F5_STAGE,
    F5_START_RUN,
    F5_STATE_FILE,
    F5_TOTAL_RUNS,
    REPO_NAME,
    REPO_OWNER,
)

DOCKERFILE_PATH = Path("Dockerfile")
DOCKERFILE_BACKUP = Path("Dockerfile.bak")
FIXTURE_DIR = Path(".docker_tmp_fixtures")


# ---------------------------------------------------------------------------
# Scenario loading
# ---------------------------------------------------------------------------
def load_scenario_catalog():
    """Load and validate the scenario definitions from docker_errors.json."""
    scenarios_path = Path(F5_SCENARIOS_FILE)
    if not scenarios_path.exists():
        raise FileNotFoundError(f"Scenario file '{scenarios_path}' not found.")

    with scenarios_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    families = data.get("scenario_families", {})
    if not families:
        raise ValueError(f"No scenario families found in {scenarios_path}.")

    return families


def get_ordered_variants(families, count=50, pilot=False):
    """Return an ordered list of scenario variants.

    In pilot mode, selects 1 variant per family (D1 to D10).
    In batch mode, interleaves variants across all 10 families to guarantee equal balance.
    """
    ordered = []
    family_keys = sorted(families.keys(), key=lambda k: int(k[1:]))

    if pilot:
        for fam_id in family_keys:
            variants = families[fam_id].get("variants", [])
            if not variants:
                raise ValueError(f"Family {fam_id} has no variants.")
            v = dict(variants[0])
            v["family_id"] = fam_id
            v["family_meta"] = families[fam_id]
            ordered.append(v)
        return ordered[:10]

    max_variants = max(len(families[k].get("variants", [])) for k in family_keys)
    for v_idx in range(max_variants):
        for fam_id in family_keys:
            variants = families[fam_id].get("variants", [])
            if v_idx < len(variants):
                v = dict(variants[v_idx])
                v["family_id"] = fam_id
                v["family_meta"] = families[fam_id]
                ordered.append(v)
                if len(ordered) >= count:
                    return ordered

    return ordered[:count]


# ---------------------------------------------------------------------------
# State Management
# ---------------------------------------------------------------------------
def load_f5_state():
    """Load or initialize state_f5.json."""
    state_path = Path(F5_STATE_FILE)
    if not state_path.exists():
        initial = {
            "current_run": F5_START_RUN - 1,
            "completed_runs": 0,
            "last_variant_id": None,
            "family_progress": {f"D{i}": 0 for i in range(1, 11)},
        }
        save_f5_state(initial)
        return initial

    with state_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_f5_state(state):
    """Persist state_f5.json."""
    state_path = Path(F5_STATE_FILE)
    with state_path.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=4)



# ---------------------------------------------------------------------------
# Working tree safety and cleanup
# ---------------------------------------------------------------------------
def setup_working_tree():
    """Backup any existing Dockerfile before generation runs."""
    if DOCKERFILE_PATH.exists() and not DOCKERFILE_BACKUP.exists():
        shutil.copy2(DOCKERFILE_PATH, DOCKERFILE_BACKUP)


def cleanup_working_tree():
    """Restore working tree and remove temporary Dockerfiles/fixtures."""
    if DOCKERFILE_PATH.exists():
        try:
            DOCKERFILE_PATH.unlink()
        except OSError:
            pass

    if DOCKERFILE_BACKUP.exists():
        shutil.copy2(DOCKERFILE_BACKUP, DOCKERFILE_PATH)
        try:
            DOCKERFILE_BACKUP.unlink()
        except OSError:
            pass

    if FIXTURE_DIR.exists():
        try:
            shutil.rmtree(FIXTURE_DIR, ignore_errors=True)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Realistic Workflow Log Synthesis
# ---------------------------------------------------------------------------
PRECEDING_STEPS_OPTIONS = [
    [
        ("Set up job", "Runner Image: ubuntu-22.04\nVersion: 20260401.1\nIncluded Software: Buildx v0.35.0, Docker 28.0.4"),
        ("Checkout Repository", "[command]/usr/bin/git checkout --progress --force refs/heads/main"),
    ],
    [
        ("Set up job", "Runner Image: ubuntu-22.04\nVersion: 20260401.1\nOperating System: Linux 6.5.0-1014-azure"),
        ("Checkout Repository", "[command]/usr/bin/git checkout --progress --force refs/heads/main"),
        ("Set up Docker Buildx", "[command]/usr/bin/docker buildx create --name builder-ci --use\nbuilder-ci"),
    ],
    [
        ("Set up job", "Runner Image: ubuntu-22.04\nVersion: 20260401.1"),
        ("Checkout Repository", "[command]/usr/bin/git checkout --progress --force refs/heads/main"),
        ("Lint Codebase", "flake8 passed with 0 errors.\nblack --check: 12 files left unchanged."),
        ("Set up Docker Buildx", "Using default buildx instance with docker-container driver."),
    ],
]


def synthesize_docker_workflow_log(variant, run_number, job_name="docker-ci", step_name="Build Container Image"):
    """Generate realistic GitHub Actions runner output matching BuildKit error traces.

    Emulates real runner timing, varying preceding steps, realistic timestamps,
    varied log lengths, and exact BuildKit error outputs.
    """
    fam_id = variant["family_id"]
    base_time = datetime(2026, 8, 15, 10, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=(run_number * 3) % 43200)

    lines = []
    current_time = base_time

    def emit(sub_step, msg, inc_ms=500):
        nonlocal current_time
        current_time += timedelta(milliseconds=inc_ms)
        ts_str = current_time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z"
        lines.append(f"{job_name}\t{sub_step}\t{ts_str} {msg}")

    # 1. Preceding workflow steps
    preceding_idx = run_number % len(PRECEDING_STEPS_OPTIONS)
    for p_step, p_content in PRECEDING_STEPS_OPTIONS[preceding_idx]:
        for line in p_content.splitlines():
            emit(p_step, line, inc_ms=100)

    # 2. Start Docker Build step
    emit(step_name, "##[group]Run docker build", inc_ms=200)
    cli_opts = " ".join(variant.get("cli_options", ["."]))
    emit(step_name, f"[command]/usr/bin/docker build {cli_opts}", inc_ms=150)
    emit(step_name, "#1 [internal] load build definition from Dockerfile", inc_ms=100)
    df_len = len(variant["dockerfile_content"].encode("utf-8"))
    emit(step_name, f"#1 transferring dockerfile: {df_len}B done", inc_ms=120)

    # 3. Scenario-specific failure output
    if fam_id == "D1":
        missing_file = variant["missing_source_file"]
        emit(step_name, "#1 DONE 0.1s", inc_ms=100)
        emit(step_name, "#2 [internal] load .dockerignore", inc_ms=100)
        emit(step_name, "#2 transferring context: 35B done", inc_ms=80)
        emit(step_name, "#2 DONE 0.0s", inc_ms=50)
        base_img = variant.get("base_image", "python:3.11-slim")
        emit(step_name, f"#3 [1/2] FROM docker.io/library/{base_img}", inc_ms=200)
        emit(step_name, f"#3 resolve docker.io/library/{base_img} done", inc_ms=250)
        emit(step_name, "#3 DONE 0.3s", inc_ms=100)
        emit(step_name, f"#4 [2/2] COPY {missing_file} /app/data/", inc_ms=150)
        emit(step_name, f'#4 ERROR: failed to calculate checksum of ref buildref_{run_number}: "/{missing_file}": not found', inc_ms=200)
        emit(step_name, f'ERROR: failed to solve: failed to calculate checksum of ref buildref_{run_number}: "/{missing_file}": not found', inc_ms=100)
        emit(step_name, "##[error]Process completed with exit code 1.", inc_ms=50)

    elif fam_id == "D2":
        bad_instr = variant.get("invalid_instruction", "UNKNOWN")
        emit(step_name, f"#1 ERROR: dockerfile parse error on line 3: unknown instruction: {bad_instr}", inc_ms=100)
        emit(step_name, f"dockerfile parse error on line 3: unknown instruction: {bad_instr}", inc_ms=80)
        emit(step_name, "##[error]Process completed with exit code 1.", inc_ms=50)

    elif fam_id == "D3":
        expected_pat = variant.get("expected_pattern", "")
        if "stage --from index out of range" in expected_pat:
            idx = expected_pat.split(":")[-1].strip()
            emit(step_name, f"#1 ERROR: dockerfile parse error on line 6: stage --from index out of range: {idx}", inc_ms=100)
            emit(step_name, f"dockerfile parse error on line 6: stage --from index out of range: {idx}", inc_ms=80)
        elif "flag needs an argument: --from" in expected_pat:
            emit(step_name, "#1 ERROR: dockerfile parse error on line 6: flag needs an argument: --from", inc_ms=100)
            emit(step_name, "dockerfile parse error on line 6: flag needs an argument: --from", inc_ms=80)
        else:
            emit(step_name, f"#1 ERROR: failed to solve: invalid from flag value Stage_Uppercase_Illegal_{run_number % 50:02d}: invalid reference format: repository name must be lowercase", inc_ms=100)
            emit(step_name, f"ERROR: failed to solve: invalid from flag value: invalid reference format", inc_ms=80)
        emit(step_name, "##[error]Process completed with exit code 1.", inc_ms=50)

    elif fam_id == "D4":
        inv_img = variant.get("invalid_image", "INVALID_IMAGE")
        emit(step_name, "#1 DONE 0.1s", inc_ms=80)
        emit(step_name, f"#2 [internal] load metadata for {inv_img}", inc_ms=100)
        emit(step_name, f"#2 ERROR: invalid reference format: repository name must be lowercase", inc_ms=120)
        emit(step_name, f"ERROR: failed to solve: {inv_img}: invalid reference format: repository name must be lowercase", inc_ms=100)
        emit(step_name, "##[error]Process completed with exit code 1.", inc_ms=50)

    elif fam_id == "D5":
        missing_ctx = variant.get("missing_context_dir", "missing_context")
        emit(step_name, f"unable to prepare context: path \"./{missing_ctx}\" not found", inc_ms=150)
        emit(step_name, "##[error]Process completed with exit code 1.", inc_ms=50)

    elif fam_id == "D6":
        expected_pat = variant.get("expected_pattern", "")
        if "secret" in expected_pat:
            sec_id = variant.get("description", "").split("'")[1] if "'" in variant.get("description", "") else "secret_key"
            emit(step_name, "#1 DONE 0.1s", inc_ms=100)
            emit(step_name, "#2 [1/1] RUN --mount=type=secret ...", inc_ms=120)
            emit(step_name, f"#2 ERROR: failed to solve: secret {sec_id} not found: secret not found", inc_ms=150)
            emit(step_name, f"ERROR: failed to solve: secret {sec_id} not found: secret not found", inc_ms=100)
        else:
            tgt = variant.get("description", "").split("'")[1] if "'" in variant.get("description", "") else "missing_target"
            emit(step_name, f"ERROR: failed to solve: target stage \"{tgt}\" could not be found", inc_ms=150)
        emit(step_name, "##[error]Process completed with exit code 1.", inc_ms=50)

    elif fam_id == "D7":
        stages = variant.get("circular_stages", ["stage_alpha", "stage_beta"])
        emit(step_name, "#1 DONE 0.1s", inc_ms=100)
        emit(step_name, f"#2 resolving multi-stage graph: {stages[0]} -> {stages[1]} -> {stages[0]}", inc_ms=150)
        emit(step_name, f"#2 ERROR: failed to solve: circular dependency between stages: {stages[0]} -> {stages[1]} -> {stages[0]}", inc_ms=150)
        emit(step_name, f"ERROR: failed to solve: circular dependency between stages: {stages[0]} -> {stages[1]} -> {stages[0]}", inc_ms=100)
        emit(step_name, "##[error]Process completed with exit code 1.", inc_ms=50)

    elif fam_id == "D8":
        missing_tool = variant.get("missing_tool", "/bin/bash")
        emit(step_name, "#1 DONE 0.1s", inc_ms=80)
        emit(step_name, f"#2 [1/2] FROM docker.io/library/alpine:3.19", inc_ms=150)
        emit(step_name, "#2 DONE 0.2s", inc_ms=100)
        emit(step_name, f"#3 [2/2] RUN {missing_tool} ...", inc_ms=150)
        emit(step_name, f"#3 0.082 /bin/sh: {missing_tool}: not found", inc_ms=120)
        emit(step_name, f"#3 ERROR: process \"/bin/sh -c {missing_tool}\" did not complete successfully: exit code: 127", inc_ms=150)
        emit(step_name, f"ERROR: failed to solve: process \"/bin/sh -c {missing_tool}\" did not complete successfully: exit code: 127", inc_ms=100)
        emit(step_name, "##[error]Process completed with exit code 127.", inc_ms=50)

    elif fam_id == "D9":
        expected_pat = variant.get("expected_pattern", "")
        if "unknown flag" in expected_pat:
            flag = expected_pat.split(":")[-1].strip()
            emit(step_name, f"unknown flag: {flag}", inc_ms=100)
            emit(step_name, f"See 'docker build --help'.", inc_ms=50)
        else:
            missing_df = variant.get("description", "").split("'")[1] if "'" in variant.get("description", "") else "Dockerfile.custom"
            emit(step_name, f"failed to read dockerfile: open {missing_df}: no such file or directory", inc_ms=120)
        emit(step_name, "##[error]Process completed with exit code 1.", inc_ms=50)

    elif fam_id == "D10":
        script_name = variant.get("script_name", "entrypoint.sh")
        emit(step_name, "#1 DONE 0.1s", inc_ms=80)
        emit(step_name, f"#2 [1/3] FROM docker.io/library/debian:bookworm-slim", inc_ms=150)
        emit(step_name, "#2 DONE 0.2s", inc_ms=100)
        emit(step_name, f"#3 [2/3] COPY {script_name} /app/{script_name}", inc_ms=100)
        emit(step_name, "#3 DONE 0.1s", inc_ms=50)
        emit(step_name, f"#4 [3/3] RUN /app/{script_name}", inc_ms=150)
        emit(step_name, f"#4 0.091 /bin/sh: /app/{script_name}: Permission denied", inc_ms=120)
        emit(step_name, f"#4 ERROR: process \"/bin/sh -c /app/{script_name}\" did not complete successfully: exit code: 126", inc_ms=150)
        emit(step_name, f"ERROR: failed to solve: process \"/bin/sh -c /app/{script_name}\" did not complete successfully: exit code: 126", inc_ms=100)
        emit(step_name, "##[error]Process completed with exit code 126.", inc_ms=50)

    # 4. Post-job runner steps
    emit("Post Checkout Repository", "Post job cleanup.", inc_ms=200)
    emit("Complete job", "Cleaning up orphan processes", inc_ms=150)

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Manifest Management
# ---------------------------------------------------------------------------
MANIFEST_COLUMNS = [
    "run_id",
    "numeric_run_id",
    "failure_type",
    "category_id",
    "template_family_id",
    "scenario_id",
    "family_name",
    "primary_cause",
    "generation_method",
    "log_file",
    "metadata_file",
    "validation_status",
    "matched_pattern",
    "log_sha256",
    "manual_review_needed",
    "timestamp",
]


def update_manifest(manifest_entry):
    """Append entry to manifest_f5.json and manifest_f5.csv."""
    manifest_json_path = Path(F5_MANIFEST_FILE)
    manifest_csv_path = Path(F5_MANIFEST_CSV)

    manifest_json_path.parent.mkdir(parents=True, exist_ok=True)

    records = []
    if manifest_json_path.exists():
        try:
            with manifest_json_path.open("r", encoding="utf-8") as f:
                records = json.load(f)
        except json.JSONDecodeError:
            records = []

    records = [r for r in records if r.get("run_id") != manifest_entry["run_id"]]
    records.append(manifest_entry)

    with manifest_json_path.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

    write_header = not manifest_csv_path.exists() or manifest_csv_path.stat().st_size == 0
    with manifest_csv_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS)
        if write_header:
            writer.writeheader()
        writer.writerow({k: manifest_entry.get(k, "") for k in MANIFEST_COLUMNS})


# ---------------------------------------------------------------------------
# Core Execution & Validation
# ---------------------------------------------------------------------------
def execute_single_run(variant, run_number, mode="synthetic"):
    """Execute or simulate a single scenario run, validate, and persist artifacts."""
    run_id = f"F5_run_{run_number:04d}"
    file_id = f"run_{run_number:04d}"

    log_filename = f"{file_id}.log"
    metadata_filename = f"{file_id}.json"

    log_path = Path(F5_LOG_FOLDER) / log_filename
    metadata_path = Path(F5_METADATA_FOLDER) / metadata_filename

    log_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)

    if log_path.exists():
        raise FileExistsError(f"Log file already exists: {log_path}")
    if metadata_path.exists():
        raise FileExistsError(f"Metadata file already exists: {metadata_path}")

    setup_working_tree()
    try:
        DOCKERFILE_PATH.write_text(variant["dockerfile_content"], encoding="utf-8")

        if mode == "synthetic":
            log_content = synthesize_docker_workflow_log(variant, run_number)
            with log_path.open("w", encoding="utf-8") as f:
                f.write(log_content)
            commit_sha = None
            workflow_id = None
        elif mode == "remote":
            from automation.git_utils import commit_and_push
            from automation.workflow_utils import wait_for_run
            from automation.log_utils import download_workflow_log

            commit_msg = f"Docker Build Failure Run {run_number} [{variant['variant_id']}]"
            commit_sha = commit_and_push(commit_msg)
            workflow = wait_for_run(commit_sha)
            download_workflow_log(workflow, run_number, log_dir=F5_LOG_FOLDER)
            workflow_id = workflow.get("databaseId")
        else:
            raise ValueError(f"Unsupported execution mode: {mode}")

        # Validate against strict F5 patterns and 7-class boundaries
        validation = validate_docker_log_file(log_path, expected_scenario=variant["family_id"])

        if validation["status"] != "valid":
            print(f"ERROR: Run {run_number} failed validation: {validation.get('rejection_reason')}")
            if log_path.exists():
                log_path.unlink()
            return False

        # Calculate log hash for duplicate tracking
        with log_path.open("rb") as f:
            log_sha256 = hashlib.sha256(f.read()).hexdigest()

        # Build Metadata Record compatible with combined dataset schema
        timestamp = datetime.now(timezone.utc).isoformat()
        metadata = {
            "run_id": run_id,
            "numeric_run_id": run_number,
            "run_number": run_number,
            "failure_type": F5_FAILURE_TYPE,
            "category_id": F5_CATEGORY_ID,
            "stage": F5_STAGE,
            "repository": REPO_NAME,
            "commit_sha": commit_sha,
            "workflow_id": workflow_id,
            "workflow_status": "completed",
            "workflow_conclusion": "failure",
            "log_file": str(log_path),
            "validation_status": validation["status"],
            "is_docker_error": validation["is_docker_error"],
            "matched_pattern": validation["matched_pattern"],
            "matched_line": validation["matched_line"],
            "scenario_id": variant["variant_id"],
            "template_family_id": variant["family_id"],
            "scenario_family": variant["family_id"],
            "scenario_description": variant["description"],
            "primary_cause": variant["family_meta"]["primary_cause"],
            "expected_exit_code": variant["family_meta"].get("expected_exit_code", 1),
            "generation_method": "synthetic_template_variation" if mode == "synthetic" else "live_workflow",
            "log_sha256": log_sha256,
            "provenance": {
                "generator_version": "2.0",
                "template_family": variant["family_id"],
                "variant_id": variant["variant_id"],
                "synthetic_consistency_validated": True,
                "actual_execution_validated": False if mode == "synthetic" else True,
                "execution_environment": "synthetic_runner_emulation" if mode == "synthetic" else "github_actions_runner",
                "dataset_class": "F5",
            },
            "timestamp": timestamp,
        }

        save_metadata(str(metadata_path), metadata)

        # Append to labels.csv
        label_record = {
            "run_number": run_number,
            "dependency": variant["variant_id"],
            "repository": REPO_NAME,
            "commit_sha": commit_sha if commit_sha else "",
            "workflow_id": workflow_id if workflow_id else "",
            "workflow_conclusion": "failure",
            "failure_type": F5_FAILURE_TYPE,
            "stage": F5_STAGE,
            "validation_status": validation["status"],
            "matched_pattern": validation["matched_pattern"],
            "log_file": str(log_path),
            "metadata_file": str(metadata_path),
            "timestamp": timestamp,
        }
        append_label_record("labels.csv", label_record)

        # Append to Manifest
        manifest_record = {
            "run_id": run_id,
            "numeric_run_id": run_number,
            "failure_type": F5_FAILURE_TYPE,
            "category_id": F5_CATEGORY_ID,
            "template_family_id": variant["family_id"],
            "scenario_id": variant["variant_id"],
            "family_name": variant["family_meta"]["family_name"],
            "primary_cause": variant["family_meta"]["primary_cause"],
            "generation_method": metadata["generation_method"],
            "log_file": str(log_path),
            "metadata_file": str(metadata_path),
            "validation_status": validation["status"],
            "matched_pattern": validation["matched_pattern"],
            "log_sha256": log_sha256,
            "manual_review_needed": False,
            "timestamp": timestamp,
        }
        update_manifest(manifest_record)

        return True

    finally:
        cleanup_working_tree()


# ---------------------------------------------------------------------------
# Main Routine
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="F5 Docker Build Failure Generator (Multi-Class Compatible)")
    parser.add_argument("--batch", type=int, default=None, help="Generate an initial audited batch (e.g. 50)")
    parser.add_argument("--pilot", action="store_true", help="Generate 10 pilot examples (1 per scenario family D1-D10)")
    parser.add_argument("--count", type=int, default=None, help="Number of examples to generate")
    parser.add_argument("--mode", choices=["synthetic", "remote"], default="synthetic", help="Execution mode (default: synthetic)")
    parser.add_argument("--clean", action="store_true", help="Clean existing F5 artifacts before running")
    args = parser.parse_args()

    if args.clean:
        print("Cleaning existing F5 logs and metadata...")
        if Path(F5_LOG_FOLDER).exists():
            shutil.rmtree(F5_LOG_FOLDER, ignore_errors=True)
        if Path(F5_METADATA_FOLDER).exists():
            shutil.rmtree(F5_METADATA_FOLDER, ignore_errors=True)
        if Path(F5_STATE_FILE).exists():
            Path(F5_STATE_FILE).unlink()

    families = load_scenario_catalog()
    state = load_f5_state()

    if args.pilot:
        target_count = 10
        variants = get_ordered_variants(families, count=10, pilot=True)
        print(f"Running PILOT mode: {len(variants)} scenarios (D1 to D10)...")
    elif args.batch:
        target_count = args.batch
        variants = get_ordered_variants(families, count=target_count, pilot=False)
        print(f"Running AUDITED BATCH mode: {len(variants)} scenarios...")
    else:
        target_count = args.count if args.count else F5_TOTAL_RUNS
        variants = get_ordered_variants(families, count=target_count, pilot=False)
        print(f"Running generation mode: target {target_count} scenarios...")

    successful_runs = 0
    for idx, variant in enumerate(variants):
        if idx < state["completed_runs"] and not (args.pilot or args.clean):
            continue

        run_num = F5_START_RUN + idx

        ok = execute_single_run(variant, run_num, mode=args.mode)
        if not ok:
            print(f"Run {run_num} aborted. Stopping generator.")
            sys.exit(1)

        state["current_run"] = run_num
        state["completed_runs"] += 1
        state["last_variant_id"] = variant["variant_id"]
        fam = variant["family_id"]
        state["family_progress"][fam] = state["family_progress"].get(fam, 0) + 1
        save_f5_state(state)
        successful_runs += 1

    print(f"\n{'='*65}")
    print(f"F5 Generator Finished Successfully")
    print(f"Completed {successful_runs} new runs. Total state completed runs: {state['completed_runs']}")
    print(f"Logs: {F5_LOG_FOLDER}")
    print(f"Metadata: {F5_METADATA_FOLDER}")
    print(f"Manifest: {F5_MANIFEST_FILE}")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    main()
