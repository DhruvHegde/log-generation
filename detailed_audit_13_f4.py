"""
detailed_audit_13_f4.py
Audits the 13 false F4 predictions (Truth=F3, Pred=F4) and runs complete metrics verification.
"""
import sys, csv, json, re
from pathlib import Path
from collections import Counter

sys.path.insert(0, ".")
from parser.log_parser import parse_log_file
from rca.engine import analyze_record

ext_data = Path("parser_rca_validation_bundle/parser_rca_validation_bundle/external_data")
raw_dir = ext_data / "raw_logs"
gt_path = ext_data / "ground_truth.csv"
cat_path = ext_data / "public_logs_catalog.csv"

# Load catalog mapping
catalog = {}
with open(cat_path, encoding="utf-8") as f:
    for r in csv.DictReader(f):
        catalog[r["log_filename"]] = r

# Load ground truth
gt = {}
with open(gt_path, encoding="utf-8") as f:
    for r in csv.DictReader(f):
        gt[r["log_filename"]] = r

CLASS_TO_F = {
    "syntax_error": "F1",
    "dependency_error": "F2",
    "test_failure": "F3",
    "timeout": "F4",
    "runtime_error": "OOS",
    "unknown": "OOS",
    None: "OOS",
}

# 1. Run evaluation on all 586 logs
results = []
f4_fps = []
confusion = Counter()

print(f"Evaluating {len(gt)} logs...", flush=True)

for i, (fn, gt_info) in enumerate(gt.items(), 1):
    truth = gt_info["true_category"]
    log_path = raw_dir / fn
    rec = parse_log_file(log_path)
    rep = analyze_record(rec)
    pred = CLASS_TO_F.get(rep.failure_class, "OOS")
    
    confusion[(truth, pred)] += 1
    
    res_item = {
        "filename": fn,
        "truth": truth,
        "pred": pred,
        "failure_class": rep.failure_class,
        "failure_subcategory": rep.failure_subcategory,
        "record": rec,
        "report": rep
    }
    results.append(res_item)
    
    if truth != "F4" and pred == "F4":
        f4_fps.append(res_item)

    if i % 100 == 0:
        print(f"  Processed {i}/{len(gt)}...", flush=True)

print(f"Total evaluated logs: {len(results)}", flush=True)
print(f"Total F4 False Positives: {len(f4_fps)}", flush=True)

# Print detailed analysis of the 13 F4 False Positives
audit_data = []

for idx, item in enumerate(f4_fps, 1):
    fn = item["filename"]
    cat_item = catalog.get(fn, {})
    repo = cat_item.get("repository", "Unknown")
    run_id = cat_item.get("run_id", fn.replace("run_", "").replace(".log", ""))
    
    rec = item["record"]
    rep = item["report"]
    log_text = rec.log_text
    lines = log_text.splitlines()
    
    # Analyze pytest evidence
    pytest_fail_matches = [line for line in lines if "FAILED " in line or "FAILURES ==" in line or "short test summary info" in line]
    pytest_run_matches = [line for line in lines if "pytest" in line.lower() or "test session starts" in line.lower() or "collected " in line.lower()]
    cancel_matches = [line for line in lines if "operation was canceled" in line.lower() or "job cancelled" in line.lower()]
    
    # Timing of cancellation relative to test output
    first_test_line = -1
    last_test_line = -1
    cancel_line = -1
    
    for i, line in enumerate(lines):
        l_lower = line.lower()
        if "test session starts" in l_lower or "collected " in l_lower or "running pytest" in l_lower:
            if first_test_line == -1:
                first_test_line = i
            last_test_line = i
        if "FAILED " in line or "== FAILURES ==" in line or "ERROR " in line or "PASSED " in line or "::" in line:
            if first_test_line == -1:
                first_test_line = i
            last_test_line = i
        if "operation was canceled" in l_lower or "job cancelled" in l_lower:
            cancel_line = i

    cancellation_timing = "Unknown"
    if cancel_line != -1:
        if first_test_line == -1:
            cancellation_timing = "Before any test output"
        elif cancel_line < first_test_line:
            cancellation_timing = "Before test output started"
        elif cancel_line > last_test_line:
            cancellation_timing = "After test output"
        else:
            cancellation_timing = "During test output execution"

    # Exact parser rule triggered
    parser_rule = f"section C2 gha_cancellation (subcategory={rec.failure_subcategory})"
    evidence_lines = rec.evidence_lines
    
    # Excerpts around cancellation & test output
    excerpts = []
    if cancel_line != -1:
        start_ctx = max(0, cancel_line - 3)
        end_ctx = min(len(lines), cancel_line + 4)
        excerpts.append("--- Cancellation context ---")
        excerpts.extend(lines[start_ctx:end_ctx])
    
    if pytest_fail_matches:
        excerpts.append("--- Pytest failure context ---")
        excerpts.extend(pytest_fail_matches[:5])
        
    audit_entry = {
        "index": idx,
        "filename": fn,
        "run_id": run_id,
        "repository": repo,
        "truth": item["truth"],
        "pred": item["pred"],
        "failure_subcategory": rec.failure_subcategory,
        "has_pytest_failure_evidence": len(pytest_fail_matches) > 0,
        "cancellation_timing": cancellation_timing,
        "first_test_line": first_test_line,
        "last_test_line": last_test_line,
        "cancel_line": cancel_line,
        "parser_rule": parser_rule,
        "evidence_lines": evidence_lines,
        "excerpts": excerpts[:10]
    }
    audit_data.append(audit_entry)

with open("f4_audit_results.json", "w", encoding="utf-8") as f:
    json.dump(audit_data, f, indent=2)

print("Saved f4_audit_results.json")
