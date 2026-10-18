REPO_OWNER = "DhruvHegde"
REPO_NAME = "dependency-error-repo"

WORKFLOW_NAME = "Success Dataset"
WORKFLOW_FILE = "ci.yml"

POLL_INTERVAL = 5
MAX_WAIT = 300

SUCCESS_TOTAL_RUNS = 300 # TEST: set to 300 for full collection
SUCCESS_FAMILY = "F1"
SUCCESS_SCENARIO = "successful_dependency_installation"
SUCCESS_STATE_FILE = "success_state.json"
SUCCESS_CSV_FILE = "success_records.csv"
SUCCESS_LOG_FOLDER = "logs/success/F1"
SUCCESS_METADATA_FOLDER = "metadata/success/F1"
SUCCESS_MAX_ATTEMPTS_PER_SAMPLE = 3