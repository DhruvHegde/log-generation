"""Helpers for saving GitHub Actions logs for completed workflow runs."""

from pathlib import Path

from config import REPO_NAME, REPO_OWNER
from automation.workflow_utils import run


LOG_DIR = Path("logs/F2")


def _as_workflow_id(workflow_run):
    """Return the workflow ID from either a workflow record or a raw identifier."""
    if isinstance(workflow_run, dict):
        workflow_id = workflow_run.get("databaseId")
        status = workflow_run.get("status")

        if workflow_id is None:
            raise ValueError("Workflow record is missing the 'databaseId' identifier.")

        if status != "completed":
            raise ValueError(
                f"Workflow run {workflow_id} is not completed. Current status: {status}"
            )

        return str(workflow_id).strip(), workflow_run

    if workflow_run is None or str(workflow_run).strip() == "":
        raise ValueError("A workflow run identifier is required to download logs.")

    return str(workflow_run).strip(), None


def _build_log_filename(run_number):
    """Build a dataset-friendly log filename from the dataset run number."""
    return f"run_{int(run_number):04d}.log"


def download_workflow_log(workflow_run, run_number, log_dir=None):
    """Download and save the GitHub Actions log for a completed workflow run.

    The input may be either the workflow object returned by wait_for_run() or a
    raw workflow ID. The filename is generated from the dataset run number so the
    file remains aligned with the dataset progression while GitHub-specific IDs are
    preserved for metadata in a later phase.

    Args:
        workflow_run: A workflow record dict from workflow_utils.wait_for_run() or a
            numeric/string workflow run identifier.
        run_number: The dataset run number used to name the saved log file.
        log_dir: Optional directory to save the log into. Defaults to logs/F2.

    Returns:
        str: The path to the saved log file.

    Raises:
        ValueError: If the workflow ID is missing or the workflow is not completed.
        FileExistsError: If the log file already exists.
        RuntimeError: If the GitHub CLI call fails or returns an empty log.
    """
    workflow_id, workflow_record = _as_workflow_id(workflow_run)

    destination_dir = Path(log_dir) if log_dir is not None else LOG_DIR
    destination_dir.mkdir(parents=True, exist_ok=True)

    destination = destination_dir / _build_log_filename(run_number)
    if destination.exists():
        raise FileExistsError(
            f"Log already exists for dataset run {run_number}: {destination}"
        )

    repo_ref = f"{REPO_OWNER}/{REPO_NAME}"
    command = f'gh run view {workflow_id} --log --repo "{repo_ref}"'

    try:
        log_text = run(command)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to download GitHub Actions log for workflow run {workflow_id}."
        ) from exc

    if not log_text or not log_text.strip():
        raise RuntimeError(
            f"GitHub Actions log for workflow run {workflow_id} is empty."
        )

    with destination.open("w", encoding="utf-8") as file_handle:
        file_handle.write(log_text)

    return str(destination)
