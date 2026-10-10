"""
audit_and_eval.py
Runs evaluation over 586 logs, verifies metrics, extracts 13 F4 false positives,
and outputs complete audit json and metric reports.
"""
import sys, csv, json, time
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

t0 = time.time()
predictions = {}
confusion = Counter()
f4_fps = []
records_dict = {}

print(f"Evaluating {len(gt)} logs...", flush=True)

for i, (fn, gt_info) in enumerate(gt.items(), 1):
    truth = gt_info["true_category"]
    log_path = raw_dir / fn
    rec = parse_log_file(log_path)
    rep = analyze_record(rec)
    pred = CLASS_TO_F.get(rep.failure_class, "OOS")
    
    predictions[fn] = {
        "truth": truth,
        "pred": pred,
        "failure_class": rep.failure_class,
        "failure_subcategory": rep.failure_subcategory,
        "confidence": rep.rca_confidence,
        "likely_cause": rep.likely_cause
    }
    confusion[(truth, pred)] += 1
    
    if truth != "F4" and pred == "F4":
        f4_fps.append((fn, truth, pred, rec, rep))

    if i % 100 == 0:
        print(f"  Processed {i}/{len(gt)} ({time.time()-t0:.1f}s)...", flush=True)

elapsed = time.time() - t0
print(f"Finished evaluating {len(gt)} logs in {elapsed:.1f}s.", flush=True)

# Compute metrics
cats = ["F1", "F2", "F3", "F4", "OOS"]
in_scope_cats = ["F1", "F2", "F3", "F4"]

total_logs = len(gt)
total_correct = sum(confusion[(c, c)] for c in cats)
overall_acc = total_correct / total_logs

inscope_total = sum(sum(confusion[(t, p)] for p in cats) for t in in_scope_cats)
inscope_correct = sum(confusion[(c, c)] for c in in_scope_cats)
inscope_acc = inscope_correct / inscope_total

# Per-category Precision, Recall, F1, Support
metrics = {}
for c in cats:
    tp = confusion[(c, c)]
    fp = sum(confusion[(t, c)] for t in cats if t != c)
    fn = sum(confusion[(c, p)] for p in cats if p != c)
    support = sum(confusion[(c, p)] for p in cats)
    
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
    
    metrics[c] = {
        "precision": prec,
        "recall": rec,
        "f1_score": f1,
        "support": support,
        "tp": tp,
        "fp": fp,
        "fn": fn
    }

eval_summary = {
    "overall_accuracy": overall_acc,
    "overall_correct": total_correct,
    "overall_total": total_logs,
    "inscope_accuracy": inscope_acc,
    "inscope_correct": inscope_correct,
    "inscope_total": inscope_total,
    "metrics_per_category": metrics,
    "confusion_matrix": {f"{t}->{p}": confusion[(t, p)] for t in cats for p in cats},
    "oos_abstention": confusion[("OOS", "OOS")] / sum(confusion[("OOS", p)] for p in cats),
    "f4_fps_count": len(f4_fps)
}

# Save versioned prediction and evaluation artifacts
with open("eval_predictions_v2_postfix.json", "w", encoding="utf-8") as f:
    json.dump(predictions, f, indent=2)

with open("eval_metrics_v2_postfix.json", "w", encoding="utf-8") as f:
    json.dump(eval_summary, f, indent=2)

print("\nSaved eval_predictions_v2_postfix.json and eval_metrics_v2_postfix.json", flush=True)

# Now inspect each of the 13 false F4 predictions in detail
audit_records = []
print(f"\n--- AUDITING {len(f4_fps)} FALSE F4 PREDICTIONS ---", flush=True)

for idx, (fn, truth, pred, rec, rep) in enumerate(f4_fps, 1):
    cat_entry = catalog.get(fn, {})
    repo = cat_entry.get("repository", "Unknown")
    run_id = cat_entry.get("run_id", fn.replace("run_", "").replace(".log", ""))
    
    log_text = rec.log_text
    lines = log_text.splitlines()
    
    # 1. Pytest failure evidence
    pytest_summary_lines = [l for l in lines if "=== short test summary info ===" in l or "=== FAILURES ===" in l]
    failed_test_lines = [l for l in lines if l.startswith("FAILED ") or " FAILED " in l or l.startswith("ERROR ") or " ERROR " in l]
    pytest_session_started = any("test session starts" in l.lower() or "collected " in l.lower() for l in lines)
    
    has_pytest_fail_evidence = len(pytest_summary_lines) > 0 or len(failed_test_lines) > 0 or len(rec.failed_test_ids) > 0
    
    # 2. Timing of cancellation relative to test output
    cancel_line_indices = [i for i, l in enumerate(lines) if "operation was canceled" in l.lower() or "job cancelled" in l.lower()]
    first_cancel = cancel_line_indices[0] if cancel_line_indices else -1
    
    test_line_indices = [i for i, l in enumerate(lines) if "test session starts" in l.lower() or "collected " in l.lower() or "::" in l or "FAILED" in l or "PASSED" in l]
    first_test = test_line_indices[0] if test_line_indices else -1
    last_test = test_line_indices[-1] if test_line_indices else -1
    
    if first_cancel == -1:
        cancel_timing = "No cancellation line found"
    elif first_test == -1:
        cancel_timing = "Before any test execution output"
    elif first_cancel < first_test:
        cancel_timing = "Before test execution started"
    elif first_cancel > last_test:
        cancel_timing = "After test execution ended"
    else:
        cancel_timing = "During test execution"
        
    # 3. Excerpts
    cancel_excerpt = []
    if first_cancel != -1:
        s = max(0, first_cancel - 3)
        e = min(len(lines), first_cancel + 4)
        cancel_excerpt = lines[s:e]
        
    audit_entry = {
        "num": idx,
        "filename": fn,
        "run_id": run_id,
        "repository": repo,
        "ground_truth": truth,
        "predicted": pred,
        "failure_subcategory": rec.failure_subcategory,
        "parser_rule": f"Detector Section C2 (gha_cancellation) -> failure_class='timeout', subcategory='{rec.failure_subcategory}'",
        "evidence_lines": rec.evidence_lines,
        "pytest_failure_evidence_exists": has_pytest_fail_evidence,
        "failed_test_ids": rec.failed_test_ids,
        "cancellation_timing": cancel_timing,
        "first_cancel_line": first_cancel,
        "first_test_line": first_test,
        "last_test_line": last_test,
        "cancel_excerpt": cancel_excerpt,
        "f3_supported_by_log": has_pytest_fail_evidence or len(test_line_indices) > 0,
    }
    audit_records.append(audit_entry)

with open("f4_audit_detailed.json", "w", encoding="utf-8") as f:
    json.dump(audit_records, f, indent=2)

print("Saved f4_audit_detailed.json", flush=True)
