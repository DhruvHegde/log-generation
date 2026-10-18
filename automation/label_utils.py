import csv
import os

LABEL_COLUMNS = [
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


def _normalize_value(value):
    if value is None:
        return ""
    return str(value)


def _ensure_label_file(path):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    if not os.path.exists(path) or os.path.getsize(path) == 0:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=LABEL_COLUMNS)
            writer.writeheader()


def append_label_record(path, record):
    if not isinstance(record, dict):
        raise ValueError("Label record must be a dictionary.")

    run_number = str(record.get("run_number", ""))
    if run_number == "":
        raise ValueError("Label record is missing a run_number.")

    _ensure_label_file(path)

    existing_runs = set()
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is not None:
            for row in reader:
                if row.get("run_number"):
                    existing_runs.add(str(row["run_number"]))

    if run_number in existing_runs:
        return False

    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LABEL_COLUMNS)
        writer.writerow({key: _normalize_value(record.get(key)) for key in LABEL_COLUMNS})

    return True
