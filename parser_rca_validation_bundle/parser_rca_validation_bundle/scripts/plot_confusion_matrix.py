#!/usr/bin/env python3
"""plot_confusion_matrix.py — Render a professional confusion-matrix heatmap.

Reads the independent ground_truth.csv labels and the parser's RCA predictions
(parser_rca_output.ndjson), maps the parser's failure_class onto the 5-category
F-scheme, and plots a clean blue/white annotated heatmap at 300 DPI.

Output -> C:/Users/aayus/Downloads/confusion_matrix.png
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

GROUND_TRUTH = Path("external_data/ground_truth.csv")
RCA_NDJSON = Path("external_data/parser_rca_output.ndjson")
OUT = Path("C:/Users/aayus/Downloads/confusion_matrix.png")

# Parser failure_class -> 5-category F-scheme
CLASS_TO_F = {
    "syntax_error": "F1",
    "dependency_error": "F2",
    "test_failure": "F3",
    "timeout": "F4",
    "runtime_error": "OOS",
    "unknown": "OOS",
    None: "OOS",
}
CATS = ["F1", "F2", "F3", "F4", "OOS"]
CAT_LABEL = {
    "F1": "F1\nSyntax",
    "F2": "F2\nDependency",
    "F3": "F3\nTest",
    "F4": "F4\nTimeout",
    "OOS": "OOS\nOut-of-Scope",
}


def load_ground_truth() -> dict[str, str]:
    return {r["log_filename"]: r["true_category"]
            for r in csv.DictReader(GROUND_TRUTH.open(encoding="utf-8"))}


def load_predictions() -> dict[str, str]:
    preds: dict[str, str] = {}
    for ln in RCA_NDJSON.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        d = json.loads(ln)
        fc = d.get("failure_class")
        preds[d["log_file"]] = CLASS_TO_F.get(fc, "OOS")
    return preds


def build_matrix(gt: dict[str, str], preds: dict[str, str]) -> np.ndarray:
    idx = {c: i for i, c in enumerate(CATS)}
    M = np.zeros((len(CATS), len(CATS)), dtype=int)
    for fn, truth in gt.items():
        pred = preds.get(fn, "OOS")
        if truth in idx and pred in idx:
            M[idx[truth], idx[pred]] += 1
    return M


def main() -> None:
    gt = load_ground_truth()
    preds = load_predictions()
    M = build_matrix(gt, preds)
    total = int(M.sum())
    correct = int(np.trace(M))
    acc = 100 * correct / total if total else 0

    # ---- Styling ----
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 12,
    })

    # Clean blue/white colormap
    blues = LinearSegmentedColormap.from_list(
        "clean_blues",
        ["#f7fbff", "#c6dbef", "#6baed6", "#2171b5", "#08306b"],
    )

    fig, ax = plt.subplots(figsize=(8.5, 7.2))

    # Normalize per-row (recall view) for color intensity, but annotate raw counts
    row_sums = M.sum(axis=1, keepdims=True)
    M_norm = np.divide(M, row_sums, out=np.zeros_like(M, dtype=float),
                       where=row_sums != 0)

    im = ax.imshow(M_norm, cmap=blues, vmin=0, vmax=1, aspect="equal")

    # Ticks
    ax.set_xticks(np.arange(len(CATS)))
    ax.set_yticks(np.arange(len(CATS)))
    ax.set_xticklabels([CAT_LABEL[c] for c in CATS], fontsize=11)
    ax.set_yticklabels([CAT_LABEL[c] for c in CATS], fontsize=11)
    ax.xaxis.set_label_position("top")
    ax.xaxis.tick_top()

    # Annotate raw counts (dark text on light cells, white on dark)
    for i in range(len(CATS)):
        for j in range(len(CATS)):
            val = M[i, j]
            frac = M_norm[i, j]
            color = "white" if frac > 0.55 else "#08306b"
            weight = "bold" if i == j else "normal"
            ax.text(j, i, str(val), ha="center", va="center",
                    color=color, fontsize=15, fontweight=weight)

    # Grid lines between cells
    ax.set_xticks(np.arange(-0.5, len(CATS), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(CATS), 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=2.5)
    ax.tick_params(which="minor", length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)

    # Labels & title
    ax.set_xlabel("Parser V2 Prediction", fontsize=13, fontweight="bold", labelpad=12)
    ax.set_ylabel("Ground Truth (independent regex labels)",
                  fontsize=13, fontweight="bold", labelpad=12)
    fig.suptitle("Parser V2 Confusion Matrix — Real-World CI/CD Logs",
                 fontsize=15, fontweight="bold", y=0.98)
    ax.set_title(f"{total} logs across public GitHub repositories   |   "
                 f"Overall accuracy = {acc:.1f}%  ({correct}/{total})",
                 fontsize=11, color="#444444", pad=28)

    # Colorbar (row-normalized intensity = recall)
    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("Row-normalized share (recall)", fontsize=10)
    cbar.ax.tick_params(labelsize=9)

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=300, bbox_inches="tight", facecolor="white")
    print(f"Saved -> {OUT}")
    print(f"Total={total}  Correct={correct}  Accuracy={acc:.1f}%")
    print("\nConfusion matrix (rows=truth, cols=pred):")
    print("        " + "  ".join(f"{c:>5}" for c in CATS))
    for i, c in enumerate(CATS):
        print(f"  {c:>4}  " + "  ".join(f"{M[i,j]:>5}" for j in range(len(CATS))))

    # Distribution sanity
    print("\nGround-truth distribution:", dict(Counter(gt.values())))
    print("Prediction distribution: ", dict(Counter(preds.get(fn, "OOS") for fn in gt)))


if __name__ == "__main__":
    main()