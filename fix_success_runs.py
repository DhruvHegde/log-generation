#!/usr/bin/env python3
"""Fix success runs: remove invalid/extra, fix metadata, regenerate missing."""

import csv
import json
import os
from pathlib import Path

LOGS_DIR = Path("logs/success/F7")
META_DIR = Path("metadata/success/F7")
LABELS_FILE = Path("labels.csv")
COUNTER_FILE = Path(".f7_success_counter")

def delete_invalid_extra():
    """Delete invalid S_F7_run_0003 and extra S_F7_run_0021, S_F7_run_0022."""
    to_delete = ["S_F7_run_0003", "S_F7_run_0021", "S_F7_run_0022"]
    for run_id in to_delete:
        log_file = LOGS_DIR / f"{run_id}.log"
        meta_file = META_DIR / f"{run_id}.json"
        if log_file.exists():
            log_file.unlink()
            print(f"Deleted {log_file}")
        if meta_file.exists():
            meta_file.unlink()
            print(f"Deleted {meta_file}")

def fix_labels_csv():
    """Remove entries for deleted runs from labels.csv."""
    if not LABELS_FILE.exists():
        return

    rows = []
    with open(LABELS_FILE, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            run_id = row.get("run_id", "")
            if run_id not in ("S_F7_run_0003", "S_F7_run_0021", "S_F7_run_0022"):
                rows.append(row)

    with open(LABELS_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Fixed labels.csv: kept {len(rows)} rows")

def fix_run_0020_metadata():
    """Fix S_F7_run_0020 metadata - status should be completed, conclusion success."""
    meta_file = META_DIR / "S_F7_run_0020.json"
    if not meta_file.exists():
        return
    with open(meta_file, "r", encoding="utf-8") as f:
        meta = json.load(f)
    meta["workflow_status"] = "completed"
    meta["workflow_conclusion"] = "success"
    meta["timestamp"] = "2026-10-18T18:51:04Z"
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    print("Fixed S_F7_run_0020 metadata")

def reset_counter():
    """Reset counter to 0 so next IDs are 0001, 0002, 0003."""
    COUNTER_FILE.write_text("0", encoding="utf-8")
    print("Reset counter to 0")

def verify_valid_runs():
    """Verify valid runs in range 0004-0020."""
    valid = []
    for i in range(4, 21):
        run_id = f"S_F7_run_{i:04d}"
        meta_file = META_DIR / f"{run_id}.json"
        if meta_file.exists():
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("validation_status") == "valid":
                valid.append(run_id)
    print(f"Valid runs in range 0004-0020: {len(valid)}")
    return valid

if __name__ == "__main__":
    print("=== Fixing success runs ===")
    verify_valid_runs()
    delete_invalid_extra()
    fix_labels_csv()
    fix_run_0020_metadata()
    reset_counter()
    print("\nDone! Now run: python generate_f7_success.py --runs 20")
    print("This will generate 3 more runs (0001, 0002, 0003) to reach 20 total.")