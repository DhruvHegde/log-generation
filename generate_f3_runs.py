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
import requests
from dotenv import load_dotenv

load_dotenv()

# Configuration
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_OWNER = os.getenv("REPO_OWNER", "DhruvHegde")
REPO_NAME = os.getenv("REPO_NAME", "dependency-error-repo")
GIT_BRANCH = os.getenv("GIT_BRANCH", "feature/f3-test-failures")
WORKFLOW_FILE = os.getenv("WORKFLOW_FILE", "f3_test.yml")

LOGS_DIR = Path("logs/F3")
METADATA_DIR = Path("metadata/F3")
LABELS_FILE = Path("labels.csv")
TEST_FILE = Path("tests/test_app.py")
BATCH_FILE = Path(".f3_batch.json")
BATCH_SIZE = 250

# Unified 23-column schema (matching F7)
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
    "github_run_id",
    "workflow_file",
    "is_synthetic",
    "failure_origin",
]

HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

ERROR_TYPES = [
    "AssertionError",
    "IndexError",
    "KeyError",
    "TypeError",
    "ValueError",
    "AttributeError",
    "ZeroDivisionError",
    "FileNotFoundError",
]


def select_error_types(count: int, seed: int | None = None) -> list[str]:
    """Select errors randomly while gently favoring less-used types."""
    rng = random.Random(seed)
    counts = {error_type: 0 for error_type in ERROR_TYPES}
    if LABELS_FILE.exists():
        with open(LABELS_FILE, "r", newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                error_type = row.get("dependency", "")
                if row.get("failure_type") == "F3" and error_type in counts:
                    counts[error_type] += 1

    selected = []
    for _ in range(count):
        weights = [1.0 / (1.0 + counts[error_type]) for error_type in ERROR_TYPES]
        error_type = rng.choices(ERROR_TYPES, weights=weights, k=1)[0]
        selected.append(error_type)
        counts[error_type] += 1
    return selected


def write_batch_spec(batch_size: int, seed: int | None = None) -> list[dict[str, object]]:
    """Write the randomized matrix consumed by the dynamic workflow."""
    error_types = select_error_types(batch_size, seed=seed)
    entries = [
        {"sample": index, "error_type": error_type}
        for index, error_type in enumerate(error_types, start=1)
    ]
    BATCH_FILE.write_text(json.dumps({"include": entries}, indent=2), encoding="utf-8")
    return entries


def sync_and_prepare_labels(clean_f3: bool, clean_s_f3: bool = False) -> tuple[int, int]:
    """Enforces canonical schema, handles isolated cleanup, and returns existing F3 and S_F3 counts."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    SUCCESS_LOGS_DIR = Path("logs/success/F3")
    SUCCESS_METADATA_DIR = Path("metadata/success/F3")
    SUCCESS_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    SUCCESS_METADATA_DIR.mkdir(parents=True, exist_ok=True)

    if clean_f3:
        for f in LOGS_DIR.glob("*"):
            if f.is_file():
                f.unlink()
        for f in METADATA_DIR.glob("*"):
            if f.is_file():
                f.unlink()

    if clean_s_f3:
        for f in SUCCESS_LOGS_DIR.glob("*"):
            if f.is_file():
                f.unlink()
        for f in SUCCESS_METADATA_DIR.glob("*"):
            if f.is_file():
                f.unlink()

    if not LABELS_FILE.exists():
        with open(LABELS_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writeheader()
        return 0, 0

    preserved_rows = []
    f3_count = 0
    s_f3_count = 0

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

            is_f3 = (
                row_dict.get("category_id") == "F3"
                or row_dict.get("failure_type") == "F3"
            )
            is_s_f3 = row_dict.get("success_family") == "F3"

            if is_f3:
                if not clean_f3:
                    preserved_rows.append(row_dict)
                    f3_count += 1
            elif is_s_f3:
                if not clean_s_f3:
                    preserved_rows.append(row_dict)
                    s_f3_count += 1
            else:
                preserved_rows.append(row_dict)

    # Overwrite file ensuring the canonical schema.
    with open(LABELS_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(preserved_rows)

    return f3_count, s_f3_count


def migrate_legacy_row(row: list[str]) -> dict[str, str]:
    """Convert the previous label layouts into the current unified 23-column registry schema."""
    # Default values for all 23 columns
    result = {column: "" for column in CSV_COLUMNS}

    if len(row) >= 13:
        # Original 13-column schema: run_number,dependency,repository,commit_sha,workflow_id,workflow_conclusion,failure_type,stage,validation_status,matched_pattern,log_file,metadata_file,timestamp
        run_number, dependency, repository, commit_sha, workflow_id, workflow_conclusion, failure_type, stage, validation_status, matched_pattern, log_file, metadata_file, timestamp = row[:13]

        result["run_id"] = f"F3_run_{run_number}" if failure_type == "F3" else run_number
        result["outcome"] = "failure" if workflow_conclusion == "failure" else "success"
        result["category_id"] = failure_type if failure_type in ["F0", "F1", "F2", "F3", "F4", "F5", "F6", "F7"] else ""
        result["failure_type"] = dependency if failure_type == "F3" else ""
        result["scenario_id"] = dependency if failure_type == "F3" else "valid_python_project"
        result["success_family"] = ""
        result["stage"] = stage
        result["workflow_id"] = workflow_id
        result["job_id"] = run_number
        result["repository"] = repository
        result["commit_sha"] = commit_sha
        result["workflow_conclusion"] = workflow_conclusion
        result["generation_method"] = "live_workflow_controlled_failure" if failure_type == "F3" else "live_workflow"
        result["actual_execution_validated"] = "true"
        result["validation_status"] = validation_status
        result["error_signature"] = matched_pattern
        result["log_file"] = log_file
        result["metadata_file"] = metadata_file
        result["timestamp"] = timestamp
        result["github_run_id"] = ""
        result["workflow_file"] = workflow_id
        result["is_synthetic"] = "true" if failure_type == "F3" else "false"
        result["failure_origin"] = "test_mutation" if failure_type == "F3" else ""
    elif len(row) == 5:
        # Even older schema
        run_number, repository, status, failure_type, stage = row
        commit_sha = ""
        workflow_id = ""
        error_type = ""

        result["run_id"] = f"F3_run_{run_number}" if failure_type == "F3" else run_number
        result["outcome"] = "failure" if status == "failure" else "success"
        result["category_id"] = failure_type if failure_type in ["F0", "F1", "F2", "F3", "F4", "F5", "F6", "F7"] else ""
        result["failure_type"] = error_type if failure_type == "F3" else ""
        result["scenario_id"] = error_type if failure_type == "F3" else "valid_python_project"
        result["success_family"] = ""
        result["stage"] = stage
        result["workflow_id"] = workflow_id
        result["job_id"] = run_number
        result["repository"] = repository
        result["commit_sha"] = commit_sha
        result["workflow_conclusion"] = status
        result["generation_method"] = "live_workflow_controlled_failure" if failure_type == "F3" else "live_workflow"
        result["actual_execution_validated"] = "true"
        result["validation_status"] = status
        result["error_signature"] = error_type
        result["log_file"] = f"logs/F3/{run_number}.log" if failure_type == "F3" else ""
        result["metadata_file"] = f"metadata/F3/{run_number}.json" if failure_type == "F3" else ""
        result["timestamp"] = ""
        result["github_run_id"] = ""
        result["workflow_file"] = workflow_id
        result["is_synthetic"] = "true" if failure_type == "F3" else "false"
        result["failure_origin"] = "test_mutation" if failure_type == "F3" else ""
    else:
        return {column: "" for column in CSV_COLUMNS}

    return result


def git_commit_and_push(batch_num: int) -> str:
    # Ensure there is a file change to commit
    timestamp_comment = f"\n# Trigger batch {batch_num} at {time.time()}\n"
    with open(TEST_FILE, "a", encoding="utf-8") as f:
        f.write(timestamp_comment)

    # Add all changes (including deletions from --clean)
    subprocess.run(["git", "add", "-A"], check=True, capture_output=True)
    commit_msg = f"synthetic(F3): parallel matrix batch run #{batch_num}"
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


def current_commit_is_f3_batch() -> bool:
    result = subprocess.run(
        ["git", "log", "-1", "--format=%s"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip().startswith("synthetic(F3):")


def current_commit_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def latest_labeled_f3_commit() -> str:
    if not LABELS_FILE.exists():
        return ""
    with open(LABELS_FILE, "r", newline="", encoding="utf-8") as stream:
        commits = [
            row.get("commit_sha", "")
            for row in csv.DictReader(stream)
            if row.get("failure_type") == "F3"
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
                    if WORKFLOW_FILE in r.get("path", "") or r.get("name") == "F3 Test Failures CI":
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
    return [job for job in unique_jobs.values() if job.get("name", "").startswith("test-f3 (")]


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


def fetch_and_save_matrix_artifacts(run: dict, commit_sha: str, expected_jobs: int):
    jobs = get_matrix_jobs(run["id"])
    if len(jobs) != expected_jobs:
        raise RuntimeError(f"Expected {expected_jobs} F3 jobs, collected {len(jobs)}")

    def download_job(job: dict) -> dict:
        job_id = job["id"]
        job_name = job.get("name", "")
        matched_error = next(
            (error_type for error_type in ERROR_TYPES if error_type in job_name),
            "AssertionError",
        )
        metadata_path = METADATA_DIR / f"{job_id}.json"
        metadata_path.write_text(json.dumps(job, indent=2), encoding="utf-8")

        log_path = LOGS_DIR / f"{job_id}.log"
        log_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/jobs/{job_id}/logs"
        log_res = requests.get(log_url, headers=HEADERS, timeout=30)
        log_text = log_res.text if log_res.status_code == 200 else f"Log retrieval failed with HTTP {log_res.status_code}"
        log_path.write_text(log_text, encoding="utf-8")

        completed_at_str = job.get("completed_at") or ""
        return {
            "job": job,
            "matched_error": matched_error,
            "metadata_path": metadata_path,
            "log_path": log_path,
            "timestamp": completed_at_str,
        }

    records = []
    with ThreadPoolExecutor(max_workers=min(32, expected_jobs)) as executor:
        futures = [executor.submit(download_job, job) for job in jobs]
        for future in as_completed(futures):
            records.append(future.result())

    with open(LABELS_FILE, "a", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS)
        for result in records:
            job = result["job"]
            job_id = job["id"]
            job_name = job.get("name", "")
            matched_error = result["matched_error"]
            metadata_path = result["metadata_path"]
            log_path = result["log_path"]
            completed_at_str = result["timestamp"]
            started_at_str = job.get("started_at")
            duration = 0.0
            if started_at_str and completed_at_str:
                started_at = datetime.fromisoformat(started_at_str.replace("Z", "+00:00"))
                completed_at = datetime.fromisoformat(completed_at_str.replace("Z", "+00:00"))
                duration = round((completed_at - started_at).total_seconds(), 2)

            conclusion = job.get("conclusion", "failure")
            record = {
                "run_id": f"F3_run_{job_id}",
                "outcome": "failure",
                "category_id": "F3",
                "failure_type": matched_error,
                "scenario_id": matched_error,
                "success_family": "",
                "stage": "test",
                "workflow_id": WORKFLOW_FILE,
                "job_id": str(job_id),
                "repository": f"{REPO_OWNER}/{REPO_NAME}",
                "commit_sha": commit_sha,
                "workflow_conclusion": conclusion,
                "generation_method": "live_workflow_controlled_failure",
                "actual_execution_validated": "true",
                "validation_status": "valid" if conclusion == "failure" else "failed_validation",
                "error_signature": f"TEST ERROR: {matched_error}",
                "log_file": str(log_path).replace("\\", "/"),
                "metadata_file": str(metadata_path).replace("\\", "/"),
                "timestamp": completed_at_str,
                "github_run_id": str(run["id"]),
                "workflow_file": WORKFLOW_FILE,
                "is_synthetic": "true",
                "failure_origin": "test_mutation",
            }
            writer.writerow(record)
            print(f"  -> Job {job_id} ({job_name}): {conclusion} [{matched_error}] ({duration}s)")

    return records


def fetch_and_save_success_artifacts(run: dict, commit_sha: str, expected_jobs: int):
    jobs = get_matrix_jobs(run["id"])
    if len(jobs) != expected_jobs:
        raise RuntimeError(f"Expected {expected_jobs} S_F3 jobs, collected {len(jobs)}")

    SUCCESS_LOGS_DIR = Path("logs/success/F3")
    SUCCESS_METADATA_DIR = Path("metadata/success/F3")
    SUCCESS_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    SUCCESS_METADATA_DIR.mkdir(parents=True, exist_ok=True)

    def download_job(job: dict) -> dict:
        job_id = job["id"]
        job_name = job.get("name", "")
        metadata_path = SUCCESS_METADATA_DIR / f"{job_id}.json"
        metadata_path.write_text(json.dumps(job, indent=2), encoding="utf-8")

        log_path = SUCCESS_LOGS_DIR / f"{job_id}.log"
        log_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/jobs/{job_id}/logs"
        log_res = requests.get(log_url, headers=HEADERS, timeout=30)
        log_text = log_res.text if log_res.status_code == 200 else f"Log retrieval failed with HTTP {log_res.status_code}"
        log_path.write_text(log_text, encoding="utf-8")

        completed_at_str = job.get("completed_at") or ""
        return {
            "job": job,
            "metadata_path": metadata_path,
            "log_path": log_path,
            "timestamp": completed_at_str,
        }

    records = []
    with ThreadPoolExecutor(max_workers=min(32, expected_jobs)) as executor:
        futures = [executor.submit(download_job, job) for job in jobs]
        for future in as_completed(futures):
            records.append(future.result())

    with open(LABELS_FILE, "a", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS)
        for result in records:
            job = result["job"]
            job_id = job["id"]
            job_name = job.get("name", "")
            metadata_path = result["metadata_path"]
            log_path = result["log_path"]
            completed_at_str = result["timestamp"]
            started_at_str = job.get("started_at")
            duration = 0.0
            if started_at_str and completed_at_str:
                started_at = datetime.fromisoformat(started_at_str.replace("Z", "+00:00"))
                completed_at = datetime.fromisoformat(completed_at_str.replace("Z", "+00:00"))
                duration = round((completed_at - started_at).total_seconds(), 2)

            conclusion = job.get("conclusion", "success")
            record = {
                "run_id": f"S_F3_run_{job_id}",
                "outcome": "success",
                "category_id": "",
                "failure_type": "",
                "scenario_id": "valid_python_project",
                "success_family": "F3",
                "stage": "test",
                "workflow_id": WORKFLOW_FILE,
                "job_id": str(job_id),
                "repository": f"{REPO_OWNER}/{REPO_NAME}",
                "commit_sha": commit_sha,
                "workflow_conclusion": conclusion,
                "generation_method": "live_workflow",
                "actual_execution_validated": "true",
                "validation_status": "valid" if conclusion == "success" else "failed_validation",
                "error_signature": "all_tests_passed",
                "log_file": str(log_path).replace("\\", "/"),
                "metadata_file": str(metadata_path).replace("\\", "/"),
                "timestamp": completed_at_str,
                "github_run_id": str(run["id"]),
                "workflow_file": WORKFLOW_FILE,
                "is_synthetic": "false",
                "failure_origin": "",
            }
            writer.writerow(record)
            print(f"  -> Job {job_id} ({job_name}): {conclusion} [success] ({duration}s)")

    return records


def main():
    parser = argparse.ArgumentParser(description="High-Speed Parallel Matrix F3 Test Failure & Success Generation Engine")
    parser.add_argument("--runs", type=int, default=500, help="Total target F3 failure runs (default: 500)")
    parser.add_argument("--success-runs", type=int, default=300, help="Total target S_F3 success runs (default: 300)")
    parser.add_argument("--clean", action="store_true", help="Purge prior F3 data before starting")
    parser.add_argument("--seed", type=int, default=None, help="Optional seed for reproducible error selection")
    args = parser.parse_args()

    if not GITHUB_TOKEN:
        raise ValueError("GITHUB_TOKEN not found in environment or .env file.")

    existing_f3_runs, existing_s_f3_runs = sync_and_prepare_labels(clean_f3=args.clean)

    def count_f3_failures() -> int:
        """Count actual F3 failure runs in labels.csv."""
        if not LABELS_FILE.exists():
            return 0
        count = 0
        with open(LABELS_FILE, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("category_id") == "F3":
                    count += 1
        return count

    def count_s_f3_successes() -> int:
        """Count actual S_F3 success runs in labels.csv."""
        if not LABELS_FILE.exists():
            return 0
        count = 0
        with open(LABELS_FILE, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("success_family") == "F3":
                    count += 1
        return count

    # Generate failures first
    existing_f3_runs = count_f3_failures()
    print(f"[F3 Progress] Failures: {existing_f3_runs}/{args.runs} | Successes: {existing_s_f3_runs}/{args.success_runs}")

    if existing_f3_runs < args.runs:
        print("Starting randomized F3 failure generator.")
        batch_number = 1
        try:
            while existing_f3_runs < args.runs:
                remaining = args.runs - existing_f3_runs
                batch_size = min(BATCH_SIZE, remaining)

                batch_entries = []
                if BATCH_FILE.exists():
                    batch_entries = json.loads(BATCH_FILE.read_text(encoding="utf-8")).get("include", [])

                can_resume_batch = (
                    not args.clean
                    and current_commit_is_f3_batch()
                    and current_commit_sha() != latest_labeled_f3_commit()
                    and len(batch_entries) == batch_size
                )
                if can_resume_batch:
                    commit_sha = current_commit_sha()
                    print(f"Resuming existing F3 workflow for commit {commit_sha[:12]}...")
                else:
                    write_batch_spec(batch_size, seed=None if args.seed is None else args.seed + batch_number)
                    commit_sha = git_commit_and_push(batch_num=batch_number)

                run_data = poll_workflow_run(commit_sha)
                wait_for_matrix_jobs(run_data, expected_jobs=batch_size)
                results = fetch_and_save_matrix_artifacts(run_data, commit_sha, expected_jobs=batch_size)

                # Count actual validated failures from this batch
                validated_in_batch = sum(1 for r in results if r["job"].get("conclusion") == "failure")
                existing_f3_runs = count_f3_failures()

                print(f"[F3 Progress] Failures: {existing_f3_runs}/{args.runs} | Successes: {existing_s_f3_runs}/{args.success_runs} (batch validated: {validated_in_batch}/{batch_size})")
                batch_number += 1
                time.sleep(1)
        finally:
            print("F3 failure generation batch run finished.")
    else:
        print(f"Target of {args.runs} F3 failure runs already reached ({existing_f3_runs} present). Skipping failure generation.")

    # Generate successes
    existing_s_f3_runs = count_s_f3_successes()
    print(f"[F3 Progress] Failures: {existing_f3_runs}/{args.runs} | Successes: {existing_s_f3_runs}/{args.success_runs}")

    if existing_s_f3_runs < args.success_runs:
        print("Starting S_F3 success generator.")
        success_batch_number = 1
        try:
            while existing_s_f3_runs < args.success_runs:
                remaining = args.success_runs - existing_s_f3_runs
                batch_size = min(BATCH_SIZE, remaining)

                # Write batch spec with all "success" error types
                entries = [{"sample": index, "error_type": "success"} for index in range(1, batch_size + 1)]
                BATCH_FILE.write_text(json.dumps({"include": entries}, indent=2), encoding="utf-8")

                commit_sha = git_commit_and_push(batch_num=success_batch_number + 1000)  # Offset to avoid collision
                run_data = poll_workflow_run(commit_sha)
                wait_for_matrix_jobs(run_data, expected_jobs=batch_size)
                results = fetch_and_save_success_artifacts(run_data, commit_sha, expected_jobs=batch_size)

                # Count actual validated successes from this batch
                validated_in_batch = sum(1 for r in results if r["job"].get("conclusion") == "success")
                existing_s_f3_runs = count_s_f3_successes()

                print(f"[F3 Progress] Failures: {existing_f3_runs}/{args.runs} | Successes: {existing_s_f3_runs}/{args.success_runs} (batch validated: {validated_in_batch}/{batch_size})")
                success_batch_number += 1
                time.sleep(1)
        finally:
            print("S_F3 success generation batch run finished.")
    else:
        print(f"Target of {args.success_runs} S_F3 success runs already reached ({existing_s_f3_runs} present). Skipping success generation.")

    print(f"\n[F3 Final] Failures: {existing_f3_runs}/{args.runs} | Successes: {existing_s_f3_runs}/{args.success_runs}")
    print("Parallel generation batch run finished.")


if __name__ == "__main__":
    main()
