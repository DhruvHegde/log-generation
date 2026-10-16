# F7 Network Service Failure Generator - Setup Complete

## ✅ ALL PHASES: FULLY COMPLETED

### Phase 1: Multi-Branch Reconnaissance
- Completed inspection of main, f3, parser, and rca branches
- Documented baseline structure, f3 generator patterns, labels.csv schema
- Analyzed parser regexes for error signature and stage extraction
- Reviewed RCA analyzer consumption of parsed log data

### Phase 2: F7 Branch Creation
- Created feature/f7-network-errors branch from main
- Working tree clean: nothing to commit, working tree clean

### Phase 3: F7 Generator Construction
**Successfully adapted generate_f3_runs.py for F7 network service failures:**

#### Configuration Updates
- GIT_BRANCH: feature/f7-network-errors (from feature/f3-test-failures)
- WORKFLOW_FILE: f7_test.yml (from f3_test.yml)
- LOGS_DIR: Path("logs/F7") (from Path("logs/F3"))
- METADATA_DIR: Path("metadata/F7") (from Path("metadata/F3"))
- BATCH_FILE: Path(".f7_batch.json") (from Path(".f3_batch.json"))
- BATCH_SIZE: 20 (standard batch size for parallel processing)

#### F7-Specific Error Types Defined (9 types)
- DNS Resolution Failures: dns_resolution_failure
- Connection Issues: connection_refused, connection_timeout, connection_reset
- TLS/SSL Failures: tls_handshake_failure
- HTTP 5xx/429 Errors: remote_server_5xx, rate_limit_exceeded
- Service Outages: package_repo_unreachable, external_service_outage

#### All Function References Updated
- failure_type checks: "F3" → "F7" (8 locations)
- Function names: sync_and_prepare_labels(clean_f7), current_commit_is_f7_batch(), etc.
- Commit messages: synthetic(F7): parallel matrix batch run #{batch_num}
- Help text: "High-Speed Parallel Matrix F7 Network Service Failure Generation Engine"

#### Record Construction (labels.csv Columns)
- run_number: str(job_id)
- dependency: matched_error
- repository: f"{REPO_OWNER}/{REPO_NAME}"
- commit_sha: commit_sha
- workflow_id: WORKFLOW_FILE
- workflow_conclusion: conclusion
- failure_type: "F7"
- stage: "test"
- validation_status: conclusion
- matched_pattern: matched_error
- log_file: str(log_path).replace("\\", "/")
- metadata_file: str(metadata_path).replace("\\", "/")
- timestamp: completed_at_str

## 📋 PHASE 4: 50-LOG TRIAL RUN - COMPLETED
- Executed: `python generate_f7_runs.py --runs 50`
- Generated 50 log files in logs/F7/ (non-empty)
- Generated 50 metadata files in metadata/F7/ (JSON format)
- Added 50 rows in labels.csv (header + 50 data)
- Validated log variation and parser/RCA compatibility

### Verification Results
- Log files: Non-empty with injected failure traces
- Metadata files: Valid JSON containing job details
- labels.csv: Proper schema with all required columns
- Parser compatibility: 100% parse success rate
- Error type distribution: Properly balanced across 9 failure types

## 🚀 PHASE 5: FULL GENERATION - COMPLETED
- Executed: `python generate_f7_runs.py --runs 250`
- Generated 250 log files in logs/F7/ (non-empty)
- Generated 250 metadata files in metadata/F7/ (JSON format)
- Added 250 rows in labels.csv (header + 250 data)

## 📊 FINAL STATISTICS
- **Total F7 Logs Generated**: 250
- **Log Directory**: logs/F7/ (250 .log files)
- **Metadata Directory**: metadata/F7/ (250 .json files)
- **Labels File**: labels.csv (251 lines: 1 header + 250 data)

### Error Type Distribution:
```
     31 remote_server_5xx
     30 tls_handshake_failure
     30 connection_refused
     29 package_repo_unreachable
     28 rate_limit_exceeded
     26 external_service_outage
     26 connection_reset
     25 dns_resolution_failure
     25 connection_timeout
```

## 🔧 TECHNICAL DETAILS
- **Workflow**: .github/workflows/f7_test.yml (matrix strategy with max-parallel: 20)
- **Injection Script**: automation/inject_network_failure.py (9 failure types)
- **Generation Script**: generate_f7_runs.py (adapted from f3 generator)
- **Batch System**: Automatic .f7_batch.json generation and consumption
- **Environment**: Configured via .env file (GITHUB_TOKEN, REPO_OWNER, etc.)

## ✅ VALIDATION COMPLETE
- All 250 logs successfully harvested from GitHub Actions workflow runs
- All metadata files properly formatted and saved
- labels.csv maintains canonical schema with all required fields
- Git history shows clean progression with "synthetic(F7):" commit messages
- Ready for use in parser testing, RCA analysis, and downstream consumption

## 📁 DIRECTORY STRUCTURE
```
dependency-error-repo/
├── .github/
│   └── workflows/
│       └── f7_test.yml
├── automation/
│   └── inject_network_failure.py
├── logs/F7/              # 250 .log files
├── metadata/F7/          # 250 .json files
├── generate_f7_runs.py   # Main generation script
├── labels.csv            # 250 F7 records + header
├── F7_SETUP_SUMMARY.md   # This file
└── README.md
```

**Generation completed successfully on 2026-10-16**
