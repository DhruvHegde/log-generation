#!/usr/bin/env python3
"""01_fetch_public_logs.py — Module II external validation, Step 1.

Fetch ~100 *failed* GitHub Actions workflow logs from public repositories via
the GitHub REST API (accessed through the authenticated `gh` CLI so we get the
5000 req/hr limit and correct redirect handling for the log-archive endpoint).

Outputs
-------
  external_data/raw_logs/run_<run_id>.log   raw terminal text of each failed run
  external_data/public_logs_catalog.csv     [log_filename, repository, run_id, license]

Design notes
------------
* GitHub retains Actions logs for public repos for ~90 days; older runs return
  410 Gone. We walk newest-first and skip anything that is gone/forbidden.
* The /logs endpoint returns a ZIP archive. The top-level `*.txt` files are the
  full per-job logs in the timestamped "bare" runner format that Aditya's
  Parser V2 understands. We concatenate them into one raw .log per run.
"""
from __future__ import annotations

import csv
import io
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

# --- configuration ---------------------------------------------------------
REPOS = [
    "pallets/flask",
    "psf/requests",
    "tiangolo/fastapi",
    "pallets/click",
    "encode/httpx",
    "pallets/werkzeug",
    "psf/black",
    "pallets/jinja",
    "encode/starlette",
    "pytest-dev/pytest",
]
# Statuses that constitute a "failed" run. failure -> F1/F2/F3, timed_out -> F4,
# cancelled -> often F4/OOS (runner killed, exit 137/143).
STATUSES = ["failure", "timed_out", "cancelled"]
PER_REPO_CAP = 100     # up to 100 downloadable failed logs per repository
TARGET = PER_REPO_CAP * len(REPOS)  # overall ceiling = per-repo cap across all repos
PER_PAGE = 100
MAX_PAGES = 8          # per (repo, status); scan deep — many older runs are 410 Gone
MIN_LOG_CHARS = 200    # skip empty / trivially small archives

RAW_DIR = Path("external_data/raw_logs")
CATALOG = Path("external_data/public_logs_catalog.csv")
META_JSON = Path("external_data/fetch_metadata.json")  # richer sidecar for the worksheet

GH = shutil.which("gh") or "gh"


def gh_json(endpoint: str):
    """Call `gh api <endpoint>` and parse JSON. Returns None on failure."""
    proc = subprocess.run([GH, "api", endpoint], capture_output=True)
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return None


def gh_bytes(endpoint: str) -> bytes | None:
    """Call `gh api <endpoint>` and return raw response bytes (e.g. a zip)."""
    proc = subprocess.run([GH, "api", endpoint], capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        return None
    return proc.stdout


_license_cache: dict[str, str] = {}


def get_license(repo: str) -> str:
    if repo in _license_cache:
        return _license_cache[repo]
    data = gh_json(f"repos/{repo}/license")
    spdx = "NOASSERTION"
    if isinstance(data, dict):
        lic = data.get("license") or {}
        spdx = lic.get("spdx_id") or lic.get("key") or "NOASSERTION"
    _license_cache[repo] = spdx
    return spdx


def list_failed_runs(repo: str) -> list[dict]:
    """Return failed workflow runs (newest first) across the tracked statuses."""
    runs: list[dict] = []
    seen: set[int] = set()
    for status in STATUSES:
        for page in range(1, MAX_PAGES + 1):
            ep = (f"repos/{repo}/actions/runs"
                  f"?status={status}&per_page={PER_PAGE}&page={page}")
            data = gh_json(ep)
            if not data or not data.get("workflow_runs"):
                break
            for r in data["workflow_runs"]:
                rid = r.get("id")
                if rid in seen:
                    continue
                seen.add(rid)
                runs.append(r)
    return runs


def download_run_log(repo: str, run_id: int) -> str | None:
    """Download + unzip a run's log archive; return concatenated raw text."""
    raw = gh_bytes(f"repos/{repo}/actions/runs/{run_id}/logs")
    if not raw:
        return None
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return None
    # Top-level *.txt are the full per-job logs; prefer those, else all txts.
    names = [n for n in zf.namelist() if n.lower().endswith(".txt")]
    top = [n for n in names if "/" not in n]
    chosen = top if top else names
    chunks: list[str] = []
    for n in sorted(chosen):
        try:
            chunks.append(zf.read(n).decode("utf-8", "replace"))
        except KeyError:
            continue
    text = "\n".join(chunks).strip()
    return text or None


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    CATALOG.parent.mkdir(parents=True, exist_ok=True)

    if not shutil.which("gh"):
        print("[FATAL] gh CLI not found on PATH.", file=sys.stderr)
        sys.exit(1)

    catalog_rows: list[dict] = []
    meta_rows: list[dict] = []
    candidates_scanned = 0

    for repo in REPOS:
        if len(catalog_rows) >= TARGET:
            break
        lic = get_license(repo)
        runs = list_failed_runs(repo)
        print(f"[{repo}] license={lic}  candidate failed runs={len(runs)}")
        repo_count = 0
        for r in runs:
            if len(catalog_rows) >= TARGET or repo_count >= PER_REPO_CAP:
                break
            candidates_scanned += 1
            run_id = r.get("id")
            text = download_run_log(repo, run_id)
            if not text or len(text) < MIN_LOG_CHARS:
                continue
            fname = f"run_{run_id}.log"
            (RAW_DIR / fname).write_text(text, encoding="utf-8")
            repo_count += 1
            catalog_rows.append({
                "log_filename": fname,
                "repository": repo,
                "run_id": run_id,
                "license": lic,
            })
            meta_rows.append({
                "log_filename": fname,
                "repository": repo,
                "run_id": run_id,
                "license": lic,
                "conclusion": r.get("conclusion"),
                "status": r.get("status"),
                "workflow_name": r.get("name"),
                "event": r.get("event"),
                "html_url": r.get("html_url"),
                "created_at": r.get("created_at"),
            })
            if len(catalog_rows) % 10 == 0:
                print(f"  ... collected {len(catalog_rows)}/{TARGET}")

    with CATALOG.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["log_filename", "repository", "run_id", "license"])
        w.writeheader()
        w.writerows(catalog_rows)

    META_JSON.write_text(json.dumps(meta_rows, indent=2), encoding="utf-8")

    repos_used = sorted({row["repository"] for row in catalog_rows})
    print("\n" + "=" * 55)
    print(f"  Fetched {len(catalog_rows)} failed logs "
          f"(scanned {candidates_scanned} candidates)")
    print(f"  Repositories: {', '.join(repos_used)}")
    print(f"  Catalog  -> {CATALOG}")
    print(f"  Raw logs -> {RAW_DIR}/")
    print("=" * 55)


if __name__ == "__main__":
    main()
