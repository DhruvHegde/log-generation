from automation.git_utils import commit_and_push
from automation.label_utils import append_label_record
from automation.log_utils import download_workflow_log
from automation.metadata_utils import save_metadata
from automation.state_utils import load_state, save_state
from automation.validator import validate_workflow_log_file
from automation.workflow_utils import wait_for_run
from datetime import datetime

from config import FAILURE_TYPE, REPO_NAME, STAGE, TOTAL_RUNS


def load_dependencies():
    with open("dependency_errors.txt") as f:
        return [
            line.strip()
            for line in f
            if line.strip() and not line.strip().startswith("#")
        ]


def update_requirements(package):
    with open("requirements.txt", "w") as f:
        f.write(package + "\n")


def main():

    state = load_state()
    dependencies = load_dependencies()

    if not dependencies:
        raise ValueError("dependency_errors.txt is empty. Add at least one dependency before running the dataset generator.")

    if TOTAL_RUNS > len(dependencies):
        raise ValueError(
            f"TOTAL_RUNS ({TOTAL_RUNS}) exceeds the number of available dependencies ({len(dependencies)}). "
            "Reduce TOTAL_RUNS or add more dependencies."
        )

    while state["current_run"] < TOTAL_RUNS:
        current = state["current_run"]
        package = dependencies[current]

        print(f"Run {current+1}")
        print(f"Dependency: {package}")

        try:
            update_requirements(package)

            sha = commit_and_push(
                f"Dependency Error Run {current+1}"
            )
            print("Commit SHA:", sha)

            workflow = wait_for_run(sha)
            print(f"Workflow completed: {workflow['databaseId']}")

            log_path = download_workflow_log(workflow, current+1)
            print(f"Downloaded log: {log_path}")

            validation = validate_workflow_log_file(log_path)
            print(f"Validation result: {validation['status']}")
            print(f"Dependency error: {validation['is_dependency_error']}")

            if validation["matched_pattern"] is not None:
                print(f"Matched pattern: {validation['matched_pattern']}")

            if validation["matched_line"] is not None:
                print(f"Matched line: {validation['matched_line']}")

            if validation["status"] != "valid":
                if validation["status"] == "error":
                    print(f"Validation error: log file could not be read or was missing: {log_path}")
                else:
                    print(f"Validation failed: log does not contain a known dependency error pattern: {log_path}")
                print("Current run failed validation and state was not advanced.")
                return

            metadata = {
                "run_number": current + 1,
                "dependency": package,
                "commit_sha": sha,
                "workflow_id": workflow["databaseId"],
                "workflow_status": workflow["status"],
                "workflow_conclusion": workflow.get("conclusion"),
                "log_file": log_path,
                "validation_status": validation["status"],
                "is_dependency_error": validation["is_dependency_error"],
                "matched_pattern": validation["matched_pattern"],
                "matched_line": validation["matched_line"],
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }

            metadata_path = f"metadata/F2/run_{(current + 1):04d}.json"

            try:
                save_metadata(metadata_path, metadata)
                print(f"Saved metadata: {metadata_path}")
            except Exception as metadata_exc:
                print(f"Metadata write failed for run {current + 1}: {metadata_exc}")
                print("Current run failed metadata persistence and state was not advanced.")
                return

            label_record = {
                "run_number": current + 1,
                "dependency": package,
                "repository": REPO_NAME,
                "commit_sha": sha,
                "workflow_id": workflow["databaseId"],
                "workflow_conclusion": workflow.get("conclusion"),
                "failure_type": FAILURE_TYPE,
                "stage": STAGE,
                "validation_status": validation["status"],
                "matched_pattern": validation["matched_pattern"],
                "log_file": log_path,
                "metadata_file": metadata_path,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }

            try:
                inserted = append_label_record("labels.csv", label_record)
                if inserted:
                    print(f"Appended label row for run {current + 1} to labels.csv")
                else:
                    print(f"Label row for run {current + 1} already exists in labels.csv")
            except Exception as label_exc:
                print(f"Label write failed for run {current + 1}: {label_exc}")
                print("Current run failed label persistence and state was not advanced.")
                return

            state["current_run"] += 1
            state["last_dependency"] = package
            save_state(state)

            print(f"Run {current + 1} completed successfully.")
            print()

        except KeyboardInterrupt:
            print("\nDataset generation interrupted by user.")
            return
        
        except Exception as exc:
            print(f"Run {current + 1} failed.")
            print(f"Reason: {exc}")
            return

    print("Dataset generation complete.")


if __name__ == "__main__":
    main()