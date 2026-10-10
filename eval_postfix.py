"""eval_postfix.py — post-fix evaluation of the 586-log external dataset."""
import sys, csv, time
from pathlib import Path
from collections import Counter

sys.path.insert(0, ".")
from parser.log_parser import parse_log_file
from rca.engine import analyze_record

ext_data = Path("parser_rca_validation_bundle/parser_rca_validation_bundle/external_data")
raw_dir = ext_data / "raw_logs"
gt_path = ext_data / "ground_truth.csv"

with open(gt_path, encoding="utf-8") as f:
    gt = {r["log_filename"]: r["true_category"] for r in csv.DictReader(f)}

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
correct = 0
confusion = Counter()
f4_correct = 0
f4_total = 0
f4_fp = []

print(f"Evaluating {len(gt)} logs...", flush=True)

for i, (fn, truth) in enumerate(gt.items(), 1):
    rec = parse_log_file(raw_dir / fn)
    rep = analyze_record(rec)
    pred = CLASS_TO_F.get(rep.failure_class, "OOS")
    confusion[(truth, pred)] += 1
    if truth == pred:
        correct += 1
    if truth == "F4":
        f4_total += 1
    if truth == "F4" and pred == "F4":
        f4_correct += 1
    if pred == "F4" and truth != "F4":
        f4_fp.append((fn, truth, rep.failure_class, rep.failure_subcategory))
    if i % 100 == 0:
        print(f"  Processed {i}/{len(gt)}...", flush=True)

elapsed = time.time() - t0
total = len(gt)
cats = ["F1", "F2", "F3", "F4", "OOS"]
inscope_c = sum(confusion.get((t, t), 0) for t in ["F1", "F2", "F3", "F4"])
inscope_n = sum(sum(confusion.get((t, p), 0) for p in cats) for t in ["F1", "F2", "F3", "F4"])

print()
print("=" * 60)
print(f"Overall accuracy   : {correct}/{total} = {correct/total*100:.1f}%")
print(f"In-scope accuracy  : {inscope_c}/{inscope_n} = {inscope_c/inscope_n*100:.1f}%")
print(f"F4 recall          : {f4_correct}/{f4_total} = {f4_correct/f4_total*100:.1f}%" if f4_total else "F4: no samples")
print(f"F4 false positives : {len(f4_fp)}")
print(f"Elapsed            : {elapsed:.1f}s")
print()
print("Confusion matrix (rows=truth, cols=pred):")
print("Truth\\Pred\t" + "\t".join(cats) + "\tTotal")
for t in cats:
    row = [str(confusion.get((t, p), 0)) for p in cats]
    total_row = sum(confusion.get((t, p), 0) for p in cats)
    print(f"{t}\t\t" + "\t".join(row) + f"\t{total_row}")
print()
if f4_fp:
    print("F4 false positives breakdown:")
    from collections import Counter as C2
    for k, v in sorted(C2(x[1] for x in f4_fp).items()):
        print(f"  Truth={k}: {v}")
else:
    print("No F4 false positives.")
