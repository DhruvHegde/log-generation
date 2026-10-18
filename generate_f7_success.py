#!/usr/bin/env python3
"""Generate 20 F7 success baseline logs (S_F7_run_0001 through S_F7_run_0020)."""

import argparse
import csv
import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
import threading
import requests
from dotenv import load_dotenv

load_dotenv()

# Configuration
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_OWNER = os.getenv("REPO_OWNER", "DhruvHegde")
REPO_NAME = os.getenv("REPO_NAME", "dependency-error-repo")
GIT_BRANCH = os.getenv("GIT_BRANCH", "feature/f7-network-errors")
WORKFLOW_FILE = os.getenv("WORKFLOW_FILE", "f7_test.yml")

SUCCESS_LOGS_DIR = Path("logs/success/F7")
SUCCESS_METADATA_DIR = Path("metadata/success/F7")
LABELS_FILE = Path("labels.csv")
TEST_FILE = Path("tests/test_app.py")
BATCH_FILE = Path(".f7_batch.json")
SUCCESS_COUNTER_FILE = Path(".f7_success_counter")
_SUCCESS_COUNTER_LOCK = threading.Lock()

CSV_COLUMNS = [
    "run_id",
    "outcome",
    "category_id",
    "failure_type",
    "scenario_id",
    "success_family",
    "stage",
    "workflow_id",
    "job_id",
    "repository",
    "commit_sha",
    "workflow_conclusion",
    "generation_method",
    "actual_execution_validated",
    "validation_status",
    "error_signature",
    "log_file",
    "metadata_file",
    "timestamp",
]

HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def _load_counter_locked(counter_file: Path) -> int:
    if counter_file.exists():
        try:
            return int(counter_file.read_text().strip())
        except (ValueError, FileNotFoundError):
            return 0
    return 0


def _save_counter_locked(counter_file: Path, value: int) -> None:
    counter_file.write_text(str(value), encoding="utf-8")


def get_next_success_id() -> str:
    """Get next sequential success ID (S_F7_run_0001, S_F7_run_0002, ...)."""
    with _SUCCESS_COUNTER_LOCK:
        counter = _load_counter_locked(SUCCESS_COUNTER_FILE)
        next_id = counter + 1
        _save_counter_locked(SUCCESS_COUNTER_FILE, next_id)
        return f"S_F7_run_{next_id:04d}"


def write_success_batch_spec(batch_size: int, seed: int | None = None) -> list[dict[str, object]]:
    """Write the randomized matrix consumed by the dynamic workflow for success runs."""
    entries = [
        {"sample": index, "error_type": "success"}
        for index in range(1, batch_size + 1)
    ]
    BATCH_FILE.write_text(json.dumps({"include": entries}, indent=2), encoding="utf-8")
    return entries


def git_commit_and_push_s(batch_num: int) -> str:
    """Commit and push with a batch spec for success runs."""
    write_success_batch_spec(batch_size=20)  # Always write 20 for full batch

    # Add a timestamp comment to trigger workflow
    timestamp_comment = f"\n# Success batch {batch_num} at {time.time()}\n"
    with open(TEST_FILE, "a", encoding="utf-8") as f:
        f.write(timestamp_comment)

    subprocess.run(["git", "add", "-A"], check=True, capture_output=True)
    commit_msg = f"synthetic(F7-success): baseline batch run #{batch_num}"
    subprocess.run(["git", "commit", "-m", commit_msg], check=True, capture_output=True)

    success = False
    for attempt in range(3):
        subprocess.run(["git", "pull", "--rebase", "origin", GIT_BRANCH], capture_output=True)
        res = subprocess.run(["git", "push", "origin", GIT_BRANCH], capture_output=True, text=True)
        if res.returncode == 0:
            success = True
            break
        time.sleep(5)
    if not success:
        raise RuntimeError(f"Git push failed: {res.stderr}")

    sha = subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True)
    return sha.stdout.strip()


def poll_workflow_run(commit_sha: str, timeout_sec: int = 360) -> dict:
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/runs"
    params = {"head_sha": commit_sha, "branch": GIT_BRANCH}
    start_time = time.time()

    while time.time() - start_time < timeout_sec:
        try:
            res = requests.get(url, headers=HEADERS, params=params, timeout=15)
            if res.status_code == 200:
                runs = res.json().get("workflow_runs", [])
                for r in runs:
                    if WORKFLOW_FILE in r.get("path", "") or r.get("name") == "F7 Network Errors CI":
                        return r
            elif res.status_code in (403, 429):
                retry_after = int(res.headers.get("Retry-After", 30))
                print(f"[Rate Limit] Backing off for {retry_after}s...")
                time.sleep(retry_after)
            elif res.status_code >= 500:
                time.sleep(10)
        except requests.exceptions.RequestException:
            time.sleep(5)
        time.sleep(2)

    raise TimeoutError(f"Workflow polling timed out for commit {commit_sha}")


def get_matrix_jobs(run_id: int) -> list[dict]:
    jobs_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/runs/{run_id}/jobs"
    jobs = []
    page = 1
    while True:
        jobs_res = None
        for attempt in range(5):
            try:
                jobs_res = requests.get(
                    jobs_url,
                    headers=HEADERS,
                    params={"per_page": 100, "page": page},
                    timeout=30,
                )
                if jobs_res.status_code == 200:
                    break
                if jobs_res.status_code in (403, 429):
                    retry_after = int(jobs_res.headers.get("Retry-After", 30))
                    print(f"[Jobs API] Backing off for {retry_after}s...")
                    time.sleep(retry_after)
                elif jobs_res.status_code >= 500:
                    delay = 2 ** attempt
                    print(f"[Jobs API] HTTP {jobs_res.status_code}; retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    break
            except requests.exceptions.RequestException as exc:
                delay = 2 ** attempt
                print(f"[Jobs API] {exc}; retrying in {delay}s...")
                time.sleep(delay)

        if jobs_res is None or jobs_res.status_code != 200:
            status = "request error" if jobs_res is None else f"HTTP {jobs_res.status_code}"
            raise RuntimeError(f"Failed to fetch jobs for run {run_id} ({status})")
        page_jobs = jobs_res.json().get("jobs", [])
        jobs.extend(page_jobs)
        if len(page_jobs) < 100:
            break
        page += 1

    unique_jobs = {job["id"]: job for job in jobs}
    return list(unique_jobs.values())


def validate_success_log(log_text: str) -> tuple[bool, str]:
    """Validate success log content - should pass all tests, no failures."""
    if not log_text or log_text.strip() == "":
        return False, "empty_log"

    # Check 1: No Python SyntaxError
    syntax_error_patterns = [
        r"SyntaxError",
        r"syntax error",
        r"Invalid syntax",
        r"EOL while scanning",
        r"unexpected EOF",
        r"IndentationError",
        r"TabError",
    ]
    for pattern in syntax_error_patterns:
        if re.search(pattern, log_text, re.IGNORECASE):
            return False, f"syntax_error:{pattern}"

    # Check 2: Pytest was executed
    pytest_patterns = [
        r"=== test session starts ===",
        r"collecting.*items",
        r"collected.*items",
        r"pytest.*",
        r"tests\/test_app\.py",
    ]
    pytest_found = False
    for pattern in pytest_patterns:
        if re.search(pattern, log_text, re.IGNORECASE):
            pytest_found = True
            break
    if not pytest_found:
        return False, "no_pytest_execution"

    # Check 3: All tests passed (no failures)
    if re.search(r"\d+ failed", log_text):
        return False, "tests_failed"

    # Check 4: No network error signatures
    network_error_patterns = [
        r"NETWORK ERROR:",
        r"ConnectionResetError",
        r"ConnectionRefusedError",
        r"socket\.timeout",
        r"ConnectTimeout",
        r"SSLCertVerificationError",
        r"HTTP Error 5\d\d",
        r"HTTP Error 429",
        r"URLError",
    ]
    for pattern in network_error_patterns:
        if re.search(pattern, log_text, re.IGNORECASE):
            return False, f"unexpected_network_error:{pattern}"

    return True, "all_tests_passed"


def create_success_metadata(job: dict, commit_sha: str, run_id: str, log_path: Path, is_valid: bool) -> dict:
    """Create structured metadata for success runs."""
    workflow_id = job.get("run_id")
    job_id = job.get("id")
    head_sha = commit_sha
    job_status = job.get("status")
    job_conclusion = job.get("conclusion")
    job_completed_at = job.get("completed_at")

    metadata = {
        "run_id": run_id,
        "outcome": "success",
        "category_id": None,
        "failure_type": None,
        "success_family": "F7",
        "scenario_id": "valid_python_project",
        "log_file": str(log_path).replace("\\", "/"),
        "generation_method": "live_workflow",
        "actual_execution_validated": is_valid,
        "workflow_id": workflow_id,
        "commit_sha": head_sha,
        "workflow_status": job_status,
        "workflow_conclusion": job_conclusion,
        "validation_status": "valid" if is_valid else "failed_validation",
        "validation_notes": "Network checks and tests passed" if is_valid else "Log validation failed",
        "timestamp": job_completed_at or "",
    }
    return metadata


def fetch_and_save_success_artifacts(run: dict, commit_sha: str, expected_jobs: int) -> list[dict]:
    """Fetch and save success matrix artifacts."""
    jobs = get_matrix_jobs(run["id"])
    # Filter for test-f7 jobs (not the prepare job)
    test_jobs = [job for job in jobs if job.get("name", "").startswith("test-f7 (")]
    print(f"  Found {len(test_jobs)} test-f7 jobs")

    if len(test_jobs) < expected_jobs:
        print(f"  Warning: Expected {expected_jobs} test-f7 jobs, found {len(test_jobs)}")

    results = []
    for job in test_jobs[:expected_jobs]:
        job_id = job["id"]
        job_name = job.get("name", "")

        run_id = get_next_success_id()

        # Download log
        log_path = SUCCESS_LOGS_DIR / f"{run_id}.log"
        SUCCESS_LOGS_DIR.mkdir(parents=True, exist_ok=True)
        log_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/jobs/{job_id}/logs"
        log_res = requests.get(log_url, headers=HEADERS, timeout=30)
        log_text = log_res.text if log_res.status_code == 200 else f"Log retrieval failed with HTTP {log_res.status_code}"
        log_path.write_text(log_text, encoding="utf-8")

        conclusion = job.get("conclusion", "success")

        # Validate log content
        is_valid, error_signature = validate_success_log(log_text)

        # Create metadata
        structured_metadata = create_success_metadata(job, commit_sha, run_id, log_path, is_valid)
        metadata_path = SUCCESS_METADATA_DIR / f"{run_id}.json"
        SUCCESS_METADATA_DIR.mkdir(parents=True, exist_ok=True)

        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(structured_metadata, f, indent=2)

        completed_at_str = job.get("completed_at") or ""
        started_at_str = job.get("started_at")
        duration = 0.0
        if started_at_str and completed_at_str:
            started_at = datetime.fromisoformat(started_at_str.replace("Z", "+00:00"))
            completed_at = datetime.fromisoformat(completed_at_str.replace("Z", "+00:00"))
            duration = round((completed_at - started_at).total_seconds(), 2)

        result = {
            "job": job,
            "run_id": run_id,
            "job_name": job_name,
            "is_valid": is_valid,
            "error_signature": error_signature,
            "metadata_path": metadata_path,
            "log_path": log_path,
            "timestamp": completed_at_str,
            "duration": duration,
            "conclusion": conclusion,
            "outcome": "success" if conclusion == "success" else "unexpected_failure",
            "validation_status": "valid" if is_valid else "failed_validation",
        }
        results.append(result)

        status_str = "[VALIDATED]" if is_valid else f"[INVALID: {error_signature}]"
        print(f"  -> Job {job_id} ({job_name}): {conclusion} ({duration}s) {status_str}")

    # Save valid results to labels.csv
    with open(LABELS_FILE, "a", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS)
        for result in results:
            if result["is_valid"]:
                record = {
                    "run_id": result["run_id"],
                    "outcome": "success",
                    "category_id": "",
                    "failure_type": "",
                    "scenario_id": "valid_python_project",
                    "success_family": "F7",
                    "stage": "test",
                    "workflow_id": str(result["job"].get("run_id", "")),
                    "job_id": str(result["job"]["id"]),
                    "repository": f"{REPO_OWNER}/{REPO_NAME}",
                    "commit_sha": commit_sha,
                    "workflow_conclusion": result["conclusion"],
                    "generation_method": "live_workflow",
                    "actual_execution_validated": str(result["is_valid"]).lower(),
                    "validation_status": result["validation_status"],
                    "error_signature": result["error_signature"],
                    "log_file": str(result["log_path"]).replace("\\", "/"),
                    "metadata_file": str(result["metadata_path"]).replace("\\", "/"),
                    "timestamp": result["timestamp"],
                }
                writer.writerow(record)

    return results


def wait_for_test_f7_jobs(run: dict, expected_jobs: int, timeout_sec: int = 900) -> None:
    """Wait for test-f7 matrix jobs to complete."""
    start_time = time.time()
    reported_jobs = set()
    print(f"Waiting for {expected_jobs} test-f7 matrix jobs to complete...")

    while time.time() - start_time < timeout_sec:
        jobs = get_matrix_jobs(run["id"])
        test_jobs = [job for job in jobs if job.get("name", "").startswith("test-f7 (")]
        completed_jobs = [job for job in test_jobs if job.get("status") == "completed"]

        for job in completed_jobs:
            if job["id"] in reported_jobs:
                continue
            reported_jobs.add(job["id"])
            print(
                f"  [Progress {len(reported_jobs)}/{expected_jobs}] "
                f"Job {job['id']} {job.get('name', '')}: {job.get('conclusion', 'unknown')}"
            )

        if len(completed_jobs) >= expected_jobs:
            return
        time.sleep(5)

    raise TimeoutError(f"Test-f7 matrix jobs timed out for workflow run {run['id']}")


def main():
    parser = argparse.ArgumentParser(description="Generate F7 success baseline logs")
    parser.add_argument("--runs", type=int, default=20, help="Total target success runs (default: 20)")
    args = parser.parse_args()

    if not GITHUB_TOKEN:
        raise ValueError("GITHUB_TOKEN not found in environment or .env file.")

    target_runs = args.runs
    print(f"Starting F7 success baseline generator - target: {target_runs} runs")

    SUCCESS_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    SUCCESS_METADATA_DIR.mkdir(parents=True, exist_ok=True)

    # Check existing success runs
    existing = len(list(SUCCESS_METADATA_DIR.glob("S_F7_run_*.json")))
    if existing >= target_runs:
        print(f"Target of {target_runs} success runs already reached ({existing} present). Exiting.")
        return

    remaining = target_runs - existing
    batch_number = 1
    BATCH_SIZE = 20

    try:
        while remaining > 0:
            batch_size = min(BATCH_SIZE, remaining)
            print(f"\nBatch {batch_number}: Generating {batch_size} success runs...")

            commit_sha = git_commit_and_push_s(batch_number)
            run_data = poll_workflow_run(commit_sha)
            wait_for_test_f7_jobs(run_data, expected_jobs=batch_size)
            fetch_and_save_success_artifacts(run_data, commit_sha, expected_jobs=batch_size)

            remaining -= batch_size
            batch_number += 1
            time.sleep(2)

    finally:
        print("\nSuccess generation batch run finished.")


if __name__ == "__main__":
    main()