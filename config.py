REPO_OWNER = "DhruvHegde"
REPO_NAME = "dependency-error-repo"

WORKFLOW_NAME = "Dependency Error Dataset"
WORKFLOW_FILE = "ci.yml"

FAILURE_TYPE = "F2"
STAGE = "build"

TOTAL_RUNS = 500

LOG_FOLDER = "logs/F2"
METADATA_FOLDER = "metadata/F2"

POLL_INTERVAL = 5
MAX_WAIT = 300

SUCCESS_TOTAL_RUNS = 300
SUCCESS_FAMILY = "F1"
SUCCESS_SCENARIO = "valid_python_project"
SUCCESS_STATE_FILE = "success_state.json"
SUCCESS_CSV_FILE = "success_records.csv"
SUCCESS_LOG_FOLDER = "logs/success/F1"
SUCCESS_METADATA_FOLDER = "metadata/success/F1"
SUCCESS_MAX_ATTEMPTS_PER_SAMPLE = 3