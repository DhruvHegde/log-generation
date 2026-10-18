REPO_OWNER = "DhruvHegde"
REPO_NAME = "dependency-error-repo"

WORKFLOW_NAME = "Dependency Error Dataset"
WORKFLOW_FILE = "ci.yml"

# --------------------------------------------------
# F2: Dependency Error (Dhruv's generator - DO NOT CHANGE)
# --------------------------------------------------
FAILURE_TYPE = "F2"
STAGE = "build"

TOTAL_RUNS = 19

LOG_FOLDER = "logs/F2"
METADATA_FOLDER = "metadata/F2"

POLL_INTERVAL = 5
MAX_WAIT = 300

# --------------------------------------------------
# F1: Syntax Error (this branch)
# --------------------------------------------------
F1_FAILURE_TYPE = "syntax_error"
F1_STAGE = "build"

F1_TOTAL_RUNS = 500

F1_LOG_FOLDER = "logs/F1"
F1_METADATA_FOLDER = "metadata/F1"

F1_STATE_FILE = "state_f1.json"