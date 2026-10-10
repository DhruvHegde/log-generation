"""
verify_non_regression.py
Fast verification of 7 specific non-regression scenarios using saved predictions and log content inspection.
"""
import sys, csv, json, re
from pathlib import Path

ext_data = Path("parser_rca_validation_bundle/parser_rca_validation_bundle/external_data")
raw_dir = ext_data / "raw_logs"

with open("eval_predictions_v2_postfix.json", encoding="utf-8") as f:
    preds = json.load(f)

cases = {
    "1_syntax_in_pytest_collection": [],
    "2_docker_wrapped_dependency": [],
    "3_ansi_colored_logs": [],
    "4_nested_tox_uv": [],
    "5_cancellation_only": [],
    "6_pytest_failure_plus_cancellation": [],
    "7_exit_code_137_143_no_cancel_text": []
}

print(f"Loaded {len(preds)} predictions. Scanning logs for feature patterns...", flush=True)

for fn, data in preds.items():
    log_path = raw_dir / fn
    with open(log_path, encoding="utf-8", errors="replace") as lf:
        log_text = lf.read()
        
    truth = data["truth"]
    pred = data["pred"]
    fclass = data["failure_class"]
    subcat = data["failure_subcategory"]
    
    l_lower = log_text.lower()
    
    # 1. Syntax inside pytest collection
    if ("syntaxerror" in l_lower or "indentationerror" in l_lower or "taberror" in l_lower) and ("collection" in l_lower or "pytest" in l_lower):
        cases["1_syntax_in_pytest_collection"].append((fn, truth, pred, fclass, subcat))

    # 2. Docker-wrapped dependency failures
    if ("docker" in l_lower or "buildkit" in l_lower or "container" in l_lower) and ("pip" in l_lower or "apt-get" in l_lower or "could not find a version" in l_lower or "no matching distribution" in l_lower or "error: failed to solve" in l_lower):
        cases["2_docker_wrapped_dependency"].append((fn, truth, pred, fclass, subcat))

    # 3. ANSI colored logs
    if "\x1b[" in log_text or "\033[" in log_text or "[36m" in log_text or "[1m" in log_text or "[91m" in log_text:
        cases["3_ansi_colored_logs"].append((fn, truth, pred, fclass, subcat))

    # 4. Nested tox/uv output
    if "tox" in l_lower or "uv " in l_lower or "uvrun" in l_lower:
        cases["4_nested_tox_uv"].append((fn, truth, pred, fclass, subcat))

    # 5. Cancellation-only (no pytest failure lines)
    if ("operation was canceled" in l_lower or "job cancelled" in l_lower) and not ("failed " in l_lower or "=== failures ===" in l_lower):
        cases["5_cancellation_only"].append((fn, truth, pred, fclass, subcat))

    # 6. Both pytest failure evidence AND cancellation
    if ("operation was canceled" in l_lower or "job cancelled" in l_lower) and ("failed " in l_lower or "=== failures ===" in l_lower or "short test summary info" in l_lower):
        cases["6_pytest_failure_plus_cancellation"].append((fn, truth, pred, fclass, subcat))

    # 7. Exit codes 137/143 without explicit cancellation text
    if ("exit code 137" in l_lower or "exit code 143" in l_lower or "code: 137" in l_lower) and not ("operation was canceled" in l_lower or "has timed out" in l_lower):
        cases["7_exit_code_137_143_no_cancel_text"].append((fn, truth, pred, fclass, subcat))

print("\n=== NON-REGRESSION VERIFICATION RESULTS ===", flush=True)
results_summary = {}

for case_name, items in cases.items():
    print(f"\nCategory: {case_name} (Total matched logs: {len(items)})", flush=True)
    results_summary[case_name] = {
        "total_matched": len(items),
        "samples": []
    }
    for item in items[:5]:
        sample_info = {
            "filename": item[0],
            "ground_truth": item[1],
            "predicted": item[2],
            "failure_class": item[3],
            "subcategory": item[4]
        }
        results_summary[case_name]["samples"].append(sample_info)
        print(f"  Log: {item[0]} | GT: {item[1]} | Pred: {item[2]} | Class: {item[3]} | Subcat: {item[4]}", flush=True)

with open("non_regression_verification.json", "w", encoding="utf-8") as f:
    json.dump(results_summary, f, indent=2)

print("\nSaved non_regression_verification.json", flush=True)
