import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import random
import subprocess
import time
from datetime import datetime
import re
import requests
import threading
from dotenv import load_dotenv

load_dotenv()

# Configuration
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_OWNER = os.getenv("REPO_OWNER", "DhruvHegde")
REPO_NAME = os.getenv("REPO_NAME", "dependency-error-repo")
GIT_BRANCH = os.getenv("GIT_BRANCH", "feature/f7-network-errors")
WORKFLOW_FILE = os.getenv("WORKFLOW_FILE", "f7_test.yml")

LOGS_DIR = Path("logs/F7")
METADATA_DIR = Path("metadata/F7")
SUCCESS_LOGS_DIR = Path("logs/success/F7")
SUCCESS_METADATA_DIR = Path("metadata/success/F7")
LABELS_FILE = Path("labels.csv")
TEST_FILE = Path("tests/test_app.py")
BATCH_FILE = Path(".f7_batch.json")
BATCH_SIZE = 50

# Sequential counters for standardized naming
FAILURE_COUNTER_FILE = Path(".f7_failure_counter")
SUCCESS_COUNTER_FILE = Path(".f7_success_counter")
_COUNTER_LOCK = threading.Lock()

# 23-column schema for labels.csv (unified schema for F7 and F3)
CSV_COLUMNS = [
    "run_id",
    "outcome",
    "category_id",
    "failure_type",
    "scenario_id",
    "success_family",
    "stage",
    "github_run_id",
    "workflow_id",
    "workflow_file",
    "job_id",
    "repository",
    "commit_sha",
    "workflow_conclusion",
    "generation_method",
    "is_synthetic",
    "failure_origin",
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

ERROR_TYPES = [
    "dns_resolution_failure",
    "connection_refused",
    "connection_timeout",
    "connection_reset",
    "tls_handshake_failure",
    "remote_server_5xx",
    "rate_limit_exceeded",
    "package_repo_unreachable",
    "external_service_outage"
]


def _load_counter_locked(counter_file: Path) -> int:
    """Load counter from file, return 0 if file doesn't exist. Assumes lock is held."""
    if counter_file.exists():
        try:
            return int(counter_file.read_text().strip())
        except (ValueError, FileNotFoundError):
            return 0
    return 0


def _save_counter_locked(counter_file: Path, value: int) -> None:
    """Save counter to file. Assumes lock is held."""
    counter_file.write_text(str(value), encoding="utf-8")


def get_next_failure_id() -> str:
    """Get next sequential failure ID (F7_run_0001, F7_run_0002, ...)."""
    with _COUNTER_LOCK:
        counter = _load_counter_locked(FAILURE_COUNTER_FILE)
        next_id = counter + 1
        _save_counter_locked(FAILURE_COUNTER_FILE, next_id)
        return f"F7_run_{next_id:04d}"


def get_next_success_id() -> str:
    """Get next sequential success ID (S_F7_run_0001, S_F7_run_0002, ...)."""
    with _COUNTER_LOCK:
        counter = _load_counter_locked(SUCCESS_COUNTER_FILE)
        next_id = counter + 1
        _save_counter_locked(SUCCESS_COUNTER_FILE, next_id)
        return f"S_F7_run_{next_id:04d}"


def select_error_types(count: int, seed: int | None = None) -> list[str]:
    """Select errors randomly while gently favoring less-used types."""
    rng = random.Random(seed)
    counts = {error_type: 0 for error_type in ERROR_TYPES}
    if LABELS_FILE.exists():
        with open(LABELS_FILE, "r", newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                error_type = row.get("failure_type", "")
                if row.get("category_id") == "F7" and error_type in counts:
                    counts[error_type] += 1

    selected = []
    for _ in range(count):
        weights = [1.0 / (1.0 + counts[error_type]) for error_type in ERROR_TYPES]
        error_type = rng.choices(ERROR_TYPES, weights=weights, k=1)[0]
        selected.append(error_type)
        counts[error_type] += 1
    return selected


def validate_f7_log(log_text: str, expected_error_type: str) -> tuple[bool, str]:
    """
    Validate F7 log content.

    Returns:
        (is_valid, error_signature):
        - is_valid: True if log passes all validation checks
        - error_signature: Brief description of the error found (for labeling)
    """
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

    # Check 3: Expected network error signature
    error_signatures = {
        "dns_resolution_failure": [
            r"NETWORK ERROR: DNS resolution failed",
            r"Could not resolve host",
            r"\[Errno -3\]",
            r"gaierror",
        ],
        "connection_refused": [
            r"NETWORK ERROR: Connection refused",
            r"ConnectionRefusedError",
            r"\[Errno 111\]",
            r"Connection refused",
        ],
        "connection_timeout": [
            r"NETWORK ERROR: Connection timeout",
            r"ConnectTimeout|ETIMEDOUT",
            r"Operation timed out",
            r"timeout",
        ],
        "connection_reset": [
            r"NETWORK ERROR: Connection reset",
            r"ConnectionResetError",
            r"\[Errno 104\]",
            r"Connection reset by peer",
        ],
        "tls_handshake_failure": [
            r"NETWORK ERROR: TLS handshake failure",
            r"SSLCertVerificationError",
            r"CERTIFICATE_VERIFY_FAILED",
            r"certificate verify failed",
        ],
        "remote_server_5xx": [
            r"NETWORK ERROR: Remote server 5xx error",
            r"HTTP Error 503",
            r"Service Unavailable",
        ],
        "rate_limit_exceeded": [
            r"NETWORK ERROR: Rate limit exceeded",
            r"HTTP Error 429",
            r"Too Many Requests",
        ],
        "package_repo_unreachable": [
            r"NETWORK ERROR: Package repository unreachable",
            r"HTTP Error 502",
            r"Bad Gateway",
        ],
        "external_service_outage": [
            r"NETWORK ERROR: External service outage",
            r"URLError",
            r"Connection refused by external service",
        ],
    }

    if expected_error_type not in error_signatures:
        return False, f"unknown_error_type:{expected_error_type}"

    signatures = error_signatures[expected_error_type]
    signature_found = False
    matched_signature = None

    for pattern in signatures:
        if re.search(pattern, log_text, re.IGNORECASE):
            signature_found = True
            matched_signature = pattern
            break

    if not signature_found:
        return False, f"expected_signature_not_found:{expected_error_type}"

    # Extract a brief error signature for labeling
    error_signature = matched_signature if matched_signature else expected_error_type
    return True, error_signature


def validate_success_log(log_text: str) -> tuple[bool, str]:
    """
    Validate S_F7 success log content.

    Returns:
        (is_valid, error_signature):
        - is_valid: True if log passes all validation checks
        - error_signature: Brief description (always "all_tests_passed" for success)
    """
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

    # Check 3: All tests passed (exit code 0)
    # Look for pytest pass indicators
    pass_patterns = [
        r"passed",
        r"=+\s*passed\s*=+",
    ]

    passed_found = False
    for pattern in pass_patterns:
        if re.search(pattern, log_text, re.IGNORECASE):
            passed_found = True
            break

    if not passed_found:
        return False, "tests_did_not_pass"

    return True, "all_tests_passed"


def fetch_and_save_success_artifacts(run: dict, commit_sha: str, expected_jobs: int) -> list[dict]:
    """Fetch and save success matrix artifacts, return list of validation results."""
    jobs = get_matrix_jobs(run["id"])
    if len(jobs) != expected_jobs:
        raise RuntimeError(f"Expected {expected_jobs} S_F7 jobs, collected {len(jobs)}")

    def process_job(job: dict) -> dict:
        job_id = job["id"]

        # Get sequential run ID for success
        run_id = get_next_success_id()

        # Download log first
        log_path = SUCCESS_LOGS_DIR / f"{run_id}.log"
        SUCCESS_LOGS_DIR.mkdir(parents=True, exist_ok=True)
        log_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/jobs/{job_id}/logs"
        log_res = requests.get(log_url, headers=HEADERS, timeout=30)
        log_text = log_res.text if log_res.status_code == 200 else f"Log retrieval failed with HTTP {log_res.status_code}"
        log_path.write_text(log_text, encoding="utf-8")

        # Get workflow conclusion
        conclusion = job.get("conclusion", "success")

        # Validate log content
        is_valid, error_signature = validate_success_log(log_text)

        # Create base metadata structure for success
        structured_metadata = create_structured_metadata(job, commit_sha, "success", is_success=True)
        metadata_path = SUCCESS_METADATA_DIR / f"{run_id}.json"
        SUCCESS_METADATA_DIR.mkdir(parents=True, exist_ok=True)

        # Update metadata with actual values after we know them
        structured_metadata["run_id"] = run_id
        structured_metadata["log_file"] = str(log_path).replace("\\", "/")
        structured_metadata["actual_execution_validated"] = is_valid  # boolean, not string
        structured_metadata["validation_status"] = "valid" if is_valid and conclusion == "success" else "failed_validation"

        # Add validation notes
        if is_valid and conclusion == "success":
            structured_metadata["validation_notes"] = "All network checks and baseline pytest tests passed"
        elif not is_valid:
            structured_metadata["validation_notes"] = f"Log validation failed: {error_signature}"
        else:
            structured_metadata["validation_notes"] = "Unexpected failure - expected success"

        # Save the updated metadata
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(structured_metadata, f, indent=2)

        completed_at_str = job.get("completed_at") or ""
        started_at_str = job.get("started_at")
        duration = 0.0
        if started_at_str and completed_at_str:
            started_at = datetime.fromisoformat(started_at_str.replace("Z", "+00:00"))
            completed_at = datetime.fromisoformat(completed_at_str.replace("Z", "+00:00"))
            duration = round((completed_at - started_at).total_seconds(), 2)

        return {
            "job": job,
            "run_id": run_id,
            "job_name": job.get("name", ""),
            "matched_error": "success",
            "is_valid": is_valid,
            "error_signature": error_signature,
            "metadata_path": metadata_path,
            "log_path": log_path,
            "timestamp": completed_at_str,
            "duration": duration,
            "conclusion": conclusion,
            "outcome": "success" if conclusion == "success" else "unexpected_failure",
            "validation_status": "validated" if is_valid and conclusion == "success" else "failed_validation",
        }

    results = []
    with ThreadPoolExecutor(max_workers=min(32, expected_jobs)) as executor:
        futures = [executor.submit(process_job, job) for job in jobs]
        for future in as_completed(futures):
            results.append(future.result())

    # Save valid results to labels.csv
    with open(LABELS_FILE, "a", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS)
        for result in results:
            if result["is_valid"]:  # Only save validated runs
                github_run_id = result["job"].get("run_id", "")
                record = {
                    "run_id": result["run_id"],
                    "outcome": result["outcome"],
                    "category_id": "",  # Empty for success runs
                    "failure_type": "",  # Empty for success runs
                    "scenario_id": "valid_python_project",
                    "success_family": "F7",
                    "stage": "test",
                    "github_run_id": github_run_id,
                    "workflow_id": github_run_id,
                    "workflow_file": "f7_test.yml",
                    "job_id": str(result["job"]["id"]),
                    "repository": f"{REPO_OWNER}/{REPO_NAME}",
                    "commit_sha": commit_sha,
                    "workflow_conclusion": result["conclusion"],
                    "generation_method": "live_workflow",
                    "is_synthetic": "true",
                    "failure_origin": "",
                    "actual_execution_validated": str(result["is_valid"]).lower(),
                    "validation_status": "valid",
                    "error_signature": "all_tests_passed",
                    "log_file": str(result["log_path"]).replace("\\", "/"),
                    "metadata_file": str(result["metadata_path"]).replace("\\", "/"),
                    "timestamp": result["timestamp"],
                }
                writer.writerow(record)
                print(f"  -> Job {result['job']['id']} ({result['job_name']}): {result['conclusion']} [SUCCESS] ({result['duration']}s) [VALIDATED]")
            else:
                print(f"  -> Job {result['job']['id']} ({result['job_name']}): {result['conclusion']} [INVALID: {result['error_signature']}] - DISCARDED")

    return results


def write_batch_spec(batch_size: int, seed: int | None = None) -> list[dict[str, object]]:
    """Write the randomized matrix consumed by the dynamic workflow."""
    error_types = select_error_types(batch_size, seed=seed)
    entries = [
        {"sample": index, "error_type": error_type}
        for index, error_type in enumerate(error_types, start=1)
    ]
    BATCH_FILE.write_text(json.dumps({"include": entries}, indent=2), encoding="utf-8")
    return entries


def sync_and_prepare_labels(clean_f7: bool = False) -> tuple[int, int]:
    """Enforces canonical schema, handles isolated cleanup, and returns existing F7 failure and success counts."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    SUCCESS_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    SUCCESS_METADATA_DIR.mkdir(parents=True, exist_ok=True)

    if clean_f7:
        for f in LOGS_DIR.glob("*"):
            if f.is_file():
                f.unlink()
        for f in METADATA_DIR.glob("*"):
            if f.is_file():
                f.unlink()
        for f in SUCCESS_LOGS_DIR.glob("*"):
            if f.is_file():
                f.unlink()
        for f in SUCCESS_METADATA_DIR.glob("*"):
            if f.is_file():
                f.unlink()
        # Reset counters when cleaning
        if FAILURE_COUNTER_FILE.exists():
            FAILURE_COUNTER_FILE.unlink()
        if SUCCESS_COUNTER_FILE.exists():
            SUCCESS_COUNTER_FILE.unlink()

    if not LABELS_FILE.exists():
        with open(LABELS_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writeheader()
        return 0, 0

    preserved_rows = []
    f7_count = 0
    s_f7_count = 0

    with open(LABELS_FILE, "r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)

        is_canonical = header == CSV_COLUMNS

        for row in reader:
            if not row:
                continue

            if is_canonical and len(row) == len(CSV_COLUMNS):
                row_dict = dict(zip(CSV_COLUMNS, row))
            else:
                row_dict = migrate_legacy_row(row)

            is_f7_failure = (
                row_dict.get("category_id") == "F7"
                or (len(row) > 2 and row[2] == "F7")
            )
            is_s_f7 = row_dict.get("success_family") == "F7"

            if is_f7_failure:
                if not clean_f7:
                    preserved_rows.append(row_dict)
                    f7_count += 1
            elif is_s_f7:
                if not clean_f7:
                    preserved_rows.append(row_dict)
                    s_f7_count += 1
            else:
                preserved_rows.append(row_dict)

    # Overwrite file ensuring the canonical schema.
    with open(LABELS_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(preserved_rows)

    return f7_count, s_f7_count


def migrate_legacy_row(row: list[str]) -> dict[str, str]:
    """Convert the previous label layouts into the current registry schema (23 columns)."""
    if len(row) >= 9:
        run_number, repository, commit_sha, workflow_id, stage = row[:5]
        failure_type, error_type, status = row[5:8]
    elif len(row) == 5:
        run_number, repository, status, failure_type, stage = row
        commit_sha = ""
        workflow_id = ""
        error_type = ""
    else:
        return {column: "" for column in CSV_COLUMNS}

    metadata_file = f"metadata/F7/{run_number}.json" if failure_type == "F7" else ""
    log_file = f"logs/F7/{run_number}.log" if failure_type == "F7" else ""
    timestamp = ""
    if metadata_file and Path(metadata_file).exists():
        with open(metadata_file, "r", encoding="utf-8") as metadata_stream:
            metadata = json.load(metadata_stream)
        timestamp = metadata.get("completed_at", "")

    # Determine if this is an F7 failure, S_F7 success, or other category
    is_f7_failure = failure_type == "F7"
    is_s_f7 = "S_F7" in run_number or (failure_type == "success" and stage == "test")

    # Map to new 23-column schema
    if is_f7_failure:
        return {
            "run_id": run_number,
            "outcome": "failure",
            "category_id": "F7",
            "failure_type": error_type if error_type in ERROR_TYPES else "dns_resolution_failure",
            "scenario_id": error_type if error_type in ERROR_TYPES else "dns_resolution_failure",
            "success_family": "",
            "stage": stage,
            "github_run_id": workflow_id,
            "workflow_id": workflow_id,
            "workflow_file": "f7_test.yml",
            "job_id": "",
            "repository": repository,
            "commit_sha": commit_sha,
            "workflow_conclusion": status,
            "generation_method": "live_workflow_controlled_failure",
            "is_synthetic": "true",
            "failure_origin": "controlled_error_injection",
            "actual_execution_validated": "true",
            "validation_status": status,
            "error_signature": error_type,
            "log_file": log_file,
            "metadata_file": metadata_file,
            "timestamp": timestamp,
        }
    elif is_s_f7:
        return {
            "run_id": run_number,
            "outcome": "success",
            "category_id": "",
            "failure_type": "",
            "scenario_id": "valid_python_project",
            "success_family": "F7",
            "stage": stage,
            "github_run_id": workflow_id,
            "workflow_id": workflow_id,
            "workflow_file": "f7_test.yml",
            "job_id": "",
            "repository": repository,
            "commit_sha": commit_sha,
            "workflow_conclusion": status,
            "generation_method": "live_workflow",
            "is_synthetic": "true",
            "failure_origin": "",
            "actual_execution_validated": "true",
            "validation_status": "valid",
            "error_signature": "all_tests_passed",
            "log_file": log_file,
            "metadata_file": metadata_file,
            "timestamp": timestamp,
        }
    else:
        # Other categories (F0-F6) - preserve as-is with empty new fields
        return {
            "run_id": run_number,
            "outcome": status,
            "category_id": failure_type if failure_type != "F7" else "",
            "failure_type": error_type,
            "scenario_id": error_type,
            "success_family": "",
            "stage": stage,
            "github_run_id": workflow_id,
            "workflow_id": workflow_id,
            "workflow_file": "",
            "job_id": "",
            "repository": repository,
            "commit_sha": commit_sha,
            "workflow_conclusion": status,
            "generation_method": "",
            "is_synthetic": "false",
            "failure_origin": "",
            "actual_execution_validated": "false",
            "validation_status": status,
            "error_signature": error_type,
            "log_file": log_file,
            "metadata_file": metadata_file,
            "timestamp": timestamp,
        }


def git_commit_and_push(batch_num: int) -> str:
    # Ensure there is a file change to commit
    timestamp_comment = f"\n# Trigger batch {batch_num} at {time.time()}\n"
    with open(TEST_FILE, "a", encoding="utf-8") as f:
        f.write(timestamp_comment)

    # Add all changes (including deletions from --clean)
    subprocess.run(["git", "add", "-A"], check=True, capture_output=True)
    commit_msg = f"synthetic(F7): parallel matrix batch run #{batch_num}"
    subprocess.run(["git", "commit", "-m", commit_msg], check=True, capture_output=True)

    success = False
    for attempt in range(3):
        # Ensure we are up to date before pushing
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


def current_commit_is_f7_batch() -> bool:
    result = subprocess.run(
        ["git", "log", "-1", "--format=%s"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip().startswith("synthetic(F7):")


def current_commit_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def latest_labeled_f7_commit() -> str:
    if not LABELS_FILE.exists():
        return ""
    with open(LABELS_FILE, "r", newline="", encoding="utf-8") as stream:
        commits = [
            row.get("commit_sha", "")
            for row in csv.DictReader(stream)
            if row.get("category_id") == "F7"
        ]
    return commits[-1] if commits else ""


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
                # Rate limit backoff
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
    return [job for job in unique_jobs.values() if job.get("name", "").startswith("test-f7 (")]


def wait_for_matrix_jobs(run: dict, expected_jobs: int, timeout_sec: int = 900) -> None:
    """Report each completed matrix job while waiting for the batch."""
    start_time = time.time()
    reported_jobs = set()
    print(f"Waiting for {expected_jobs} matrix jobs to complete...")

    while time.time() - start_time < timeout_sec:
        jobs = get_matrix_jobs(run["id"])
        completed_jobs = [job for job in jobs if job.get("status") == "completed"]
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

    raise TimeoutError(f"Matrix jobs timed out for workflow run {run['id']}")


def create_structured_metadata(job: dict, commit_sha: str, expected_error_type: str, is_success: bool = False) -> dict:
    """Create structured metadata with required top-level keys for team's merger script."""
    # Determine values based on whether this is a success or failure run
    if is_success:
        category_id = None
        failure_type = None
        success_family = "F7"
        scenario_id = "valid_python_project"
        outcome = "success"
        failure_origin = None
    else:
        category_id = "F7"
        failure_type = "network_service_failure"
        success_family = None
        scenario_id = expected_error_type  # e.g., "connection_reset", "dns_resolution_failure", etc.
        outcome = "failure"
        failure_origin = "controlled_error_injection"

    # Extract data from job
    github_run_id = job.get("run_id")  # GitHub workflow execution run ID
    job_id = job.get("id")  # GitHub job ID
    head_sha = commit_sha
    job_status = job.get("status")
    job_conclusion = job.get("conclusion")
    job_completed_at = job.get("completed_at")

    # Build the metadata with required top-level keys (unified schema)
    metadata = {
        "run_id": "",  # Will be filled in later by the caller
        "outcome": outcome,
        "category_id": category_id,
        "failure_type": failure_type,
        "scenario_id": scenario_id,
        "success_family": success_family,
        "log_file": "",  # Will be filled in later by the caller
        "generation_method": "live_workflow_controlled_failure" if not is_success else "live_workflow",
        "is_synthetic": True,
        "failure_origin": failure_origin,
        "actual_execution_validated": "",  # Will be filled in later by the caller after validation
        "github_run_id": github_run_id,
        "workflow_id": github_run_id,  # Alias for backward compatibility
        "workflow_file": "f7_test.yml",
        "commit_sha": head_sha,
        "workflow_status": job_status,
        "workflow_conclusion": job_conclusion,
        "validation_status": "",  # Will be filled in later by the caller after validation
        "validation_notes": "",  # Will be filled in later by the caller
        "timestamp": job_completed_at or "",
    }

    return metadata


def fetch_and_save_matrix_artifacts(run: dict, commit_sha: str, expected_jobs: int) -> list[dict]:
    """Fetch and save matrix artifacts, return list of validation results."""
    jobs = get_matrix_jobs(run["id"])
    if len(jobs) != expected_jobs:
        raise RuntimeError(f"Expected {expected_jobs} F7 jobs, collected {len(jobs)}")

    def process_job(job: dict) -> dict:
        job_id = job["id"]
        job_name = job.get("name", "")

        # Determine expected error type from job name
        matched_error = next(
            (error_type for error_type in ERROR_TYPES if error_type in job_name),
            "dns_resolution_failure",  # fallback
        )

        # Get sequential run ID
        run_id = get_next_failure_id()

        # Download log first
        log_path = LOGS_DIR / f"{run_id}.log"
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        log_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/jobs/{job_id}/logs"
        log_res = requests.get(log_url, headers=HEADERS, timeout=30)
        log_text = log_res.text if log_res.status_code == 200 else f"Log retrieval failed with HTTP {log_res.status_code}"
        log_path.write_text(log_text, encoding="utf-8")

        # Get workflow conclusion
        conclusion = job.get("conclusion", "failure")

        # Validate log content
        is_valid, error_signature = validate_f7_log(log_text, matched_error)

        # Create base metadata structure
        structured_metadata = create_structured_metadata(job, commit_sha, matched_error, is_success=False)
        metadata_path = METADATA_DIR / f"{run_id}.json"
        METADATA_DIR.mkdir(parents=True, exist_ok=True)

        # Update metadata with actual values after we know them
        structured_metadata["run_id"] = run_id
        structured_metadata["log_file"] = str(log_path).replace("\\", "/")
        structured_metadata["actual_execution_validated"] = is_valid  # boolean, not string
        structured_metadata["validation_status"] = "valid" if is_valid and conclusion == "failure" else "failed_validation"

        # Add validation notes
        if is_valid and conclusion == "failure":
            structured_metadata["validation_notes"] = f"Confirmed controlled F7 {matched_error} failure in pytest execution"
        elif not is_valid:
            structured_metadata["validation_notes"] = f"Log validation failed: {error_signature}"
        else:
            structured_metadata["validation_notes"] = "Unexpected success - expected failure"

        # Save the updated metadata (success_family is null for failures, which is correct per schema)
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(structured_metadata, f, indent=2)

        completed_at_str = job.get("completed_at") or ""
        started_at_str = job.get("started_at")
        duration = 0.0
        if started_at_str and completed_at_str:
            started_at = datetime.fromisoformat(started_at_str.replace("Z", "+00:00"))
            completed_at = datetime.fromisoformat(completed_at_str.replace("Z", "+00:00"))
            duration = round((completed_at - started_at).total_seconds(), 2)

        return {
            "job": job,
            "run_id": run_id,
            "job_name": job_name,
            "matched_error": matched_error,
            "is_valid": is_valid,
            "error_signature": error_signature,
            "metadata_path": metadata_path,
            "log_path": log_path,
            "timestamp": completed_at_str,
            "duration": duration,
            "conclusion": conclusion,
            "outcome": "failure" if conclusion == "failure" else "unexpected_success",
            "validation_status": "validated" if is_valid and conclusion == "failure" else "failed_validation",
        }

    results = []
    with ThreadPoolExecutor(max_workers=min(32, expected_jobs)) as executor:
        futures = [executor.submit(process_job, job) for job in jobs]
        for future in as_completed(futures):
            results.append(future.result())

    # Save valid results to labels.csv
    with open(LABELS_FILE, "a", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS)
        for result in results:
            if result["is_valid"]:  # Only save validated runs
                github_run_id = result["job"].get("run_id", "")
                record = {
                    "run_id": result["run_id"],
                    "outcome": result["outcome"],
                    "category_id": "F7",
                    "failure_type": result["matched_error"],
                    "scenario_id": result["matched_error"],  # Use the error type as scenario_id
                    "success_family": "",  # Empty for failure runs (null in JSON)
                    "stage": "test",
                    "github_run_id": github_run_id,
                    "workflow_id": github_run_id,  # Alias for backward compatibility
                    "workflow_file": "f7_test.yml",
                    "job_id": str(result["job"]["id"]),
                    "repository": f"{REPO_OWNER}/{REPO_NAME}",
                    "commit_sha": commit_sha,
                    "workflow_conclusion": result["conclusion"],
                    "generation_method": "live_workflow_controlled_failure",
                    "is_synthetic": "true",
                    "failure_origin": "controlled_error_injection",
                    "actual_execution_validated": str(result["is_valid"]).lower(),
                    "validation_status": result["validation_status"],
                    "error_signature": result["error_signature"],
                    "log_file": str(result["log_path"]).replace("\\", "/"),
                    "metadata_file": str(result["metadata_path"]).replace("\\", "/"),
                    "timestamp": result["timestamp"],
                }
                writer.writerow(record)
                print(f"  -> Job {result['job']['id']} ({result['job_name']}): {result['conclusion']} [{result['matched_error']}] ({result['duration']}s) [VALIDATED]")
            else:
                print(f"  -> Job {result['job']['id']} ({result['job_name']}): {result['conclusion']} [{result['matched_error']}] ({result['duration']}s) [INVALID: {result['error_signature']}] - DISCARDED")

    return results


def main():
    parser = argparse.ArgumentParser(description="High-Speed Parallel Matrix F7 Network Service Failure & Success Generation Engine")
    parser.add_argument("--runs", type=int, default=500, help="Total target F7 failure runs (default: 500)")
    parser.add_argument("--success-runs", type=int, default=300, help="Total target S_F7 success runs (default: 300)")
    parser.add_argument("--clean", action="store_true", help="Purge prior F7 data before starting")
    parser.add_argument("--seed", type=int, default=None, help="Optional seed for reproducible error selection")
    args = parser.parse_args()

    if not GITHUB_TOKEN:
        raise ValueError("GITHUB_TOKEN not found in environment or .env file.")

    existing_f7_runs, existing_s_f7_runs = sync_and_prepare_labels(clean_f7=args.clean)

    def count_f7_failures() -> int:
        """Count actual F7 failure runs in labels.csv."""
        if not LABELS_FILE.exists():
            return 0
        count = 0
        with open(LABELS_FILE, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("category_id") == "F7":
                    count += 1
        return count

    def count_s_f7_successes() -> int:
        """Count actual S_F7 success runs in labels.csv."""
        if not LABELS_FILE.exists():
            return 0
        count = 0
        with open(LABELS_FILE, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("success_family") == "F7":
                    count += 1
        return count

    # Generate failures first
    existing_f7_runs = count_f7_failures()
    print(f"[F7 Progress] Failures: {existing_f7_runs}/{args.runs} | Successes: {existing_s_f7_runs}/{args.success_runs}")

    if existing_f7_runs < args.runs:
        print("Starting randomized F7 failure generator.")
        batch_number = 1
        try:
            while existing_f7_runs < args.runs:
                remaining = args.runs - existing_f7_runs
                batch_size = min(BATCH_SIZE, remaining)

                batch_entries = []
                if BATCH_FILE.exists():
                    batch_entries = json.loads(BATCH_FILE.read_text(encoding="utf-8")).get("include", [])

                can_resume_batch = (
                    not args.clean
                    and current_commit_is_f7_batch()
                    and current_commit_sha() != latest_labeled_f7_commit()
                    and len(batch_entries) == batch_size
                )
                if can_resume_batch:
                    commit_sha = current_commit_sha()
                    print(f"Resuming existing F7 workflow for commit {commit_sha[:12]}...")
                else:
                    write_batch_spec(batch_size, seed=None if args.seed is None else args.seed + batch_number)
                    commit_sha = git_commit_and_push(batch_num=batch_number)

                run_data = poll_workflow_run(commit_sha, timeout_sec=1800)
                wait_for_matrix_jobs(run_data, expected_jobs=batch_size, timeout_sec=1800)
                results = fetch_and_save_matrix_artifacts(run_data, commit_sha, expected_jobs=batch_size)

                # Count actual validated failures from this batch
                validated_in_batch = sum(1 for r in results if r["is_valid"])
                existing_f7_runs = count_f7_failures()

                print(f"[F7 Progress] Failures: {existing_f7_runs}/{args.runs} | Successes: {existing_s_f7_runs}/{args.success_runs} (batch validated: {validated_in_batch}/{batch_size})")
                batch_number += 1
                time.sleep(1)
        finally:
            print("F7 failure generation batch run finished.")
    else:
        print(f"Target of {args.runs} F7 failure runs already reached ({existing_f7_runs} present). Skipping failure generation.")

    # Generate successes
    existing_s_f7_runs = count_s_f7_successes()
    print(f"[F7 Progress] Failures: {existing_f7_runs}/{args.runs} | Successes: {existing_s_f7_runs}/{args.success_runs}")

    if existing_s_f7_runs < args.success_runs:
        print("Starting S_F7 success generator.")
        success_batch_number = 1
        try:
            while existing_s_f7_runs < args.success_runs:
                remaining = args.success_runs - existing_s_f7_runs
                batch_size = min(BATCH_SIZE, remaining)

                # Write batch spec with all "success" error types
                entries = [{"sample": index, "error_type": "success"} for index in range(1, batch_size + 1)]
                BATCH_FILE.write_text(json.dumps({"include": entries}, indent=2), encoding="utf-8")

                commit_sha = git_commit_and_push(batch_num=success_batch_number + 1000)  # Offset to avoid collision
                run_data = poll_workflow_run(commit_sha, timeout_sec=1800)
                wait_for_matrix_jobs(run_data, expected_jobs=batch_size, timeout_sec=1800)
                results = fetch_and_save_success_artifacts(run_data, commit_sha, expected_jobs=batch_size)

                # Count actual validated successes from this batch
                validated_in_batch = sum(1 for r in results if r["is_valid"])
                existing_s_f7_runs = count_s_f7_successes()

                print(f"[F7 Progress] Failures: {existing_f7_runs}/{args.runs} | Successes: {existing_s_f7_runs}/{args.success_runs} (batch validated: {validated_in_batch}/{batch_size})")
                success_batch_number += 1
                time.sleep(1)
        finally:
            print("S_F7 success generation batch run finished.")
    else:
        print(f"Target of {args.success_runs} S_F7 success runs already reached ({existing_s_f7_runs} present). Skipping success generation.")

    print(f"\n[F7 Final] Failures: {existing_f7_runs}/{args.runs} | Successes: {existing_s_f7_runs}/{args.success_runs}")
    print("Parallel generation batch run finished.")


if __name__ == "__main__":
    main()
