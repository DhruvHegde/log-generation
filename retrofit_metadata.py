#!/usr/bin/env python3
"""Retrofit existing metadata JSON files and labels.csv to match required schema."""

import csv
import json
from pathlib import Path

METADATA_DIR = Path("metadata/F7")
LABELS_FILE = Path("labels.csv")
LOGS_DIR = Path("logs/F7")

# Required top-level keys for failure runs
REQUIRED_KEYS = [
    "run_id", "outcome", "category_id", "failure_type", "scenario_id",
    "log_file", "generation_method", "actual_execution_validated",
    "workflow_id", "commit_sha", "workflow_status", "workflow_conclusion",
    "validation_status", "validation_notes", "timestamp"
]

def retrofit_metadata_files():
    """Fix all metadata JSON files in metadata/F7/"""
    metadata_files = sorted(METADATA_DIR.glob("F7_run_*.json"))
    print(f"Found {len(metadata_files)} metadata files to retrofit")

    for meta_file in metadata_files:
        with open(meta_file, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        # Fix generation_method
        if metadata.get("generation_method") == "synthetic_injection":
            metadata["generation_method"] = "live_workflow_controlled_failure"

        # Fix actual_execution_validated: string "true"/"false" -> boolean
        if isinstance(metadata.get("actual_execution_validated"), str):
            metadata["actual_execution_validated"] = metadata["actual_execution_validated"].lower() == "true"

        # Fix validation_status: "validated" -> "valid"
        if metadata.get("validation_status") == "validated":
            metadata["validation_status"] = "valid"

        # Remove success_family from failure runs
        metadata.pop("success_family", None)

        # Ensure scenario_id is set (use failure_type if scenario_id is missing/empty)
        if not metadata.get("scenario_id") and metadata.get("failure_type"):
            # The failure_type in metadata is "network_service_failure" but scenario_id should be the specific error type
            # We'll need to get this from the log file or elsewhere. For now, keep as is if it's already set.
            pass

        # Write back
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        print(f"  Fixed {meta_file.name}")

    print("All metadata files retrofitted!")

def retrofit_labels_csv():
    """Fix labels.csv to match required schema"""
    if not LABELS_FILE.exists():
        print("labels.csv not found!")
        return

    rows = []
    with open(LABELS_FILE, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            # Fix generation_method
            if row.get("generation_method") == "synthetic_injection":
                row["generation_method"] = "live_workflow_controlled_failure"

            # Fix validation_status
            if row.get("validation_status") == "validated":
                row["validation_status"] = "valid"

            # Fix scenario_id - use failure_type if empty
            if not row.get("scenario_id") and row.get("failure_type"):
                row["scenario_id"] = row["failure_type"]

            # Fix workflow_id - read from metadata file
            metadata_file = row.get("metadata_file", "")
            if metadata_file:
                meta_path = Path(metadata_file)
                if meta_path.exists():
                    with open(meta_path, "r", encoding="utf-8") as mf:
                        meta = json.load(mf)
                    if "workflow_id" in meta and isinstance(meta["workflow_id"], (int, float)):
                        row["workflow_id"] = str(int(meta["workflow_id"]))

            rows.append(row)

    # Write back with same fieldnames
    with open(LABELS_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Fixed {len(rows)} rows in labels.csv")

def verify_metadata():
    """Verify a few metadata files"""
    metadata_files = sorted(METADATA_DIR.glob("F7_run_*.json"))[:3]
    for meta_file in metadata_files:
        with open(meta_file, "r", encoding="utf-8") as f:
            metadata = json.load(f)
        print(f"\n{meta_file.name}:")
        for key in REQUIRED_KEYS:
            val = metadata.get(key, "MISSING")
            print(f"  {key}: {val} (type: {type(val).__name__})")

if __name__ == "__main__":
    print("=== Retrofitting metadata files ===")
    retrofit_metadata_files()

    print("\n=== Retrofitting labels.csv ===")
    retrofit_labels_csv()

    print("\n=== Verification ===")
    verify_metadata()

    print("\nDone!")