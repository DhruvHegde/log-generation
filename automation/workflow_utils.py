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


def get_workflow_runs():

    command = (
    f'gh run list '
    f'--repo "{REPO_OWNER}/{REPO_NAME}" '
    f'--workflow "{WORKFLOW_FILE}" '
    '--event push '
    '--limit 20 '
    '--json databaseId,headSha,status,conclusion'
)

    output = run(command)

    return json.loads(output)


def wait_for_run(commit_sha):

    elapsed = 0

    print(f"Waiting for workflow of SHA: {commit_sha}")

    while elapsed < MAX_WAIT:

        runs = get_workflow_runs()

        print(f"\nPolling... {elapsed}s")

        for workflow in runs:

            print(
                f"Run ID={workflow['databaseId']} "
                f"SHA={workflow['headSha']} "
                f"Status={workflow['status']}"
            )

            if workflow["headSha"] == commit_sha:

                print("MATCH FOUND!")

                if workflow["status"] == "completed":
                    print("Workflow completed.")
                    return workflow

        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    raise TimeoutError("Timed out waiting for GitHub Actions.")