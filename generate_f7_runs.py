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
GIT_BRANCH = os.getenv("GIT_BRANCH", "feature/f7-network-errors")
WORKFLOW_FILE = os.getenv("WORKFLOW_FILE", "f7_test.yml")

LOGS_DIR = Path("logs/F7")
METADATA_DIR = Path("metadata/F7")
LABELS_FILE = Path("labels.csv")
TEST_FILE = Path("tests/test_app.py")
BATCH_FILE = Path(".f7_batch.json")
BATCH_SIZE = 20

CSV_COLUMNS = [
    "run_number",
    "dependency",
    "repository",
    "commit_sha",
    "workflow_id",
    "workflow_conclusion",
    "failure_type",
    "stage",
    "validation_status",
    "matched_pattern",
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


def select_error_types(count: int, seed: int | None = None) -> list[str]:
    """Select errors randomly while gently favoring less-used types."""
    rng = random.Random(seed)
    counts = {error_type: 0 for error_type in ERROR_TYPES}
    if LABELS_FILE.exists():
        with open(LABELS_FILE, "r", newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                error_type = row.get("dependency", "")
                if row.get("failure_type") == "F7" and error_type in counts:
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


def sync_and_prepare_labels(clean_f7: bool = False) -> int:
    """Enforces canonical schema, handles isolated cleanup, and returns existing F7 count."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    METADATA_DIR.mkdir(parents=True, exist_ok=True)

    if clean_f7:
        for f in LOGS_DIR.glob("*"):
            if f.is_file():
                f.unlink()
        for f in METADATA_DIR.glob("*"):
            if f.is_file():
                f.unlink()

    if not LABELS_FILE.exists():
        with open(LABELS_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writeheader()
        return 0

    preserved_rows = []
    f7_count = 0

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

            is_f7 = (
                row_dict.get("failure_type") == "F7"
                or (len(row) > 5 and row[5] == "F7")
                or (len(row) > 3 and row[3] == "F7")
            )

            if is_f7:
                if not clean_f7:
                    preserved_rows.append(row_dict)
                    f7_count += 1
            else:
                preserved_rows.append(row_dict)

    # Overwrite file ensuring the canonical schema.
    with open(LABELS_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(preserved_rows)

    return f7_count


def migrate_legacy_row(row: list[str]) -> dict[str, str]:
    """Convert the previous label layouts into the current registry schema."""
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

    return {
        "run_number": run_number,
        "dependency": error_type,
        "repository": repository,
        "commit_sha": commit_sha,
        "workflow_id": workflow_id,
        "workflow_conclusion": status,
        "failure_type": failure_type,
        "stage": stage,
        "validation_status": status,
        "matched_pattern": error_type,
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
            if row.get("failure_type") == "F7"
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
        raise RuntimeError(f"Expected {expected_jobs} F7 jobs, collected {len(jobs)}")

    def download_job(job: dict) -> dict:
        job_id = job["id"]
        job_name = job.get("name", "")
        matched_error = next(
            (error_type for error_type in ERROR_TYPES if error_type in job_name),
            "dns_resolution_failure",
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
                "run_number": str(job_id),
                "dependency": matched_error,
                "repository": f"{REPO_OWNER}/{REPO_NAME}",
                "commit_sha": commit_sha,
                "workflow_id": WORKFLOW_FILE,
                "workflow_conclusion": conclusion,
                "failure_type": "F7",
                "stage": "test",
                "validation_status": conclusion,
                "matched_pattern": matched_error,
                "log_file": str(log_path).replace("\\", "/"),
                "metadata_file": str(metadata_path).replace("\\", "/"),
                "timestamp": completed_at_str,
            }
            writer.writerow(record)
            print(f"  -> Job {job_id} ({job_name}): {conclusion} [{matched_error}] ({duration}s)")


def main():
    parser = argparse.ArgumentParser(description="High-Speed Parallel Matrix F7 Network Service Failure Generation Engine")
    parser.add_argument("--runs", type=int, default=500, help="Total target F7 runs (default: 500)")
    parser.add_argument("--clean", action="store_true", help="Purge prior F7 data before starting")
    parser.add_argument("--seed", type=int, default=None, help="Optional seed for reproducible error selection")
    args = parser.parse_args()

    if not GITHUB_TOKEN:
        raise ValueError("GITHUB_TOKEN not found in environment or .env file.")

    existing_f7_runs = sync_and_prepare_labels(clean_f7=args.clean)
    
    if existing_f7_runs >= args.runs:
        print(f"Target of {args.runs} F7 runs already reached ({existing_f7_runs} present). Exiting.")
        return

    remaining = args.runs - existing_f7_runs
    batch_number = 1
    total_batches_needed = (remaining + BATCH_SIZE - 1) // BATCH_SIZE  # Ceiling division
    print("Starting randomized F7 generator.")
    try:
        while remaining > 0:
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
            run_data = poll_workflow_run(commit_sha)
            wait_for_matrix_jobs(run_data, expected_jobs=batch_size)
            total_harvested = existing_f7_runs + (args.runs - remaining)
            fetch_and_save_matrix_artifacts(run_data, commit_sha, expected_jobs=batch_size)
            print(f"Batch {batch_number}/{total_batches_needed} complete | Total F7 logs harvested: {total_harvested}/{args.runs}")
            remaining -= batch_size
            batch_number += 1
            time.sleep(1)

    finally:
        print("Parallel generation batch run finished.")


if __name__ == "__main__":
    main()
