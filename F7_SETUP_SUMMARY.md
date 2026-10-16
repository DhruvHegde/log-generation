# F7 Network Service Failure Generator - Setup Complete

## ✅ Phases 1-3: FULLY COMPLETED

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
- BATCH_SIZE: 250 (unchanged)

#### F7-Specific Error Types Defined
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

## 📋 READY FOR PHASE 4 EXECUTION

All components are properly configured and ready for the 50-log trial run:

### Created Files
- .github/workflows/f7_test.yml - F7 workflow (triggers on feature/f7-network-errors)
- automation/inject_network_failure.py - F7 injection script (6 network failure types)
- logs/F7/ directory (for job logs)
- metadata/F7/ directory (for job metadata)
- .f7_batch.json (batch specification file)

### Verified Configuration
- generate_f7_runs.py correctly adapted for F7
- .env properly configured (GIT_BRANCH=feature/f7-network-errors, WORKFLOW_FILE=f7_test.yml)
- All F3 references replaced with F7 equivalents
- Script compiles successfully: python -m py_compile generate_f7_runs.py

### Current Status
Background process shows:
- Generator successfully creating batch specifications
- Generator committing and pushing with "synthetic(F7):" messages
- Workflow triggering confirmed by recent commits
- Ready for Phase 4: 50-log trial run and validation

## 🚀 NEXT STEPS FOR PHASE 4
Execute: `python generate_f7_runs.py --runs 50`
Then validate:
- 50 log files in logs/F7/ (non-empty)
- 50 metadata files in metadata/F7/ (JSON format)
- 50 rows in labels.csv (header + 50 data)
- Log variation analysis (line counts, error positions)
- Parser/RCA validation (100% parse success)
