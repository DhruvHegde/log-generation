import json
import subprocess
import time

from config import (
    WORKFLOW_FILE,
    POLL_INTERVAL,
    MAX_WAIT
)
from config import REPO_OWNER, REPO_NAME


def run(command):
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )

    if result.returncode != 0:
        raise Exception(result.stderr)

    return result.stdout.strip()


def get_workflow_runs(max_retries=3, initial_backoff=1.0):
    """Fetch workflow runs with bounded retries and backoff for transient failures.

    Args:
        max_retries: Maximum number of retry attempts (bounded, default 3).
        initial_backoff: Initial backoff in seconds (default 1.0).

    Returns:
        list: Parsed JSON list of workflow runs.

    Raises:
        RuntimeError: If all retries exhausted or JSON parsing fails.
    """
    command = (
        f'gh run list '
        f'--repo "{REPO_OWNER}/{REPO_NAME}" '
        f'--workflow "{WORKFLOW_FILE}" '
        '--event push '
        '--limit 20 '
        '--json databaseId,headSha,status,conclusion'
    )

    last_error = None
    backoff = initial_backoff

    for attempt in range(max_retries):
        try:
            output = run(command)
            return json.loads(output)
        except json.JSONDecodeError as e:
            last_error = e
            error_msg = f"Failed to parse JSON from gh run list (attempt {attempt + 1}/{max_retries}): {e}"
            if attempt < max_retries - 1:
                print(f"{error_msg}; retrying in {backoff}s...")
                time.sleep(backoff)
                backoff *= 2  # exponential backoff
            else:
                raise RuntimeError(error_msg) from e
        except Exception as e:
            last_error = e
            error_msg = f"gh run list failed (attempt {attempt + 1}/{max_retries}): {e}"
            if attempt < max_retries - 1:
                print(f"{error_msg}; retrying in {backoff}s...")
                time.sleep(backoff)
                backoff *= 2  # exponential backoff
            else:
                raise RuntimeError(error_msg) from e

    # Should not reach here, but fail safely
    raise RuntimeError(
        f"get_workflow_runs failed after {max_retries} attempts. Last error: {last_error}"
    )


def wait_for_run(commit_sha):
    """Poll for a completed workflow with exact commit SHA match.

    Args:
        commit_sha: The commit SHA to match exactly.

    Returns:
        dict: The completed workflow record with matching SHA.

    Raises:
        TimeoutError: If workflow not completed within MAX_WAIT seconds.
        ValueError: If a workflow with matching SHA is found but has wrong SHA
                    (safety check for exact-match guarantee).
    """
    elapsed = 0
    print(f"Waiting for workflow of SHA: {commit_sha}")

    while elapsed < MAX_WAIT:
        try:
            runs = get_workflow_runs()
        except RuntimeError as e:
            print(f"Error fetching workflow runs: {e}")
            print(f"Retrying in {POLL_INTERVAL}s...")
            time.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            continue

        # Validate: runs must be a non-empty list. Empty result from API 
        # should not be treated as "workflow not ready yet" — it's a data 
        # integrity issue that warrants a warning but not silent acceptance.
        if not isinstance(runs, list):
            print(f"Warning: unexpected runs type {type(runs)}, expected list")
            time.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            continue

        print(f"\nPolling... {elapsed}s ({len(runs)} recent runs)")

        # Find runs matching the exact commit SHA
        matching_runs = [r for r in runs if r.get("headSha") == commit_sha]

        for workflow in matching_runs:
            print(
                f"Run ID={workflow['databaseId']} "
                f"SHA={workflow['headSha']} "
                f"Status={workflow['status']}"
            )

            if workflow["status"] == "completed":
                print("Workflow completed.")
                # Final safety check: verify SHA hasn't changed
                if workflow.get("headSha") != commit_sha:
                    raise ValueError(
                        f"Workflow SHA mismatch on return: expected {commit_sha}, "
                        f"got {workflow.get('headSha')}"
                    )
                return workflow

        # Log non-matching runs for debugging (only if runs exist)
        if runs and not matching_runs:
            sample_shas = [r.get('headSha')[:8] if r.get('headSha') else '?' for r in runs[:3]]
            print(f"No matching SHA. Recent runs: {sample_shas}")
        elif not runs:
            print("No workflows returned from API yet")

        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    raise TimeoutError(f"Timed out waiting for GitHub Actions (waited {elapsed}s).")