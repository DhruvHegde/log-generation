import argparse
from pathlib import Path

TEST_FILE = Path("tests/test_app.py")

ERROR_MUTATIONS = {
    "AssertionError": """
def test_assertion_failure():
    \"\"\"Injected synthetic AssertionError.\"\"\"
    expected_status = 200
    actual_status = 500
    assert actual_status == expected_status, f"Expected {expected_status}, received {actual_status}"
""",
    "IndexError": """
def test_index_error():
    \"\"\"Injected synthetic IndexError.\"\"\"
    from src.app import get_list_item
    dataset = [10, 20, 30]
    get_list_item(dataset, 999)
""",
    "KeyError": """
def test_key_error():
    \"\"\"Injected synthetic KeyError.\"\"\"
    from src.app import get_dict_value
    config = {"env": "staging", "retries": 3}
    get_dict_value(config, "missing_auth_token")
""",
    "TypeError": """
def test_type_error():
    \"\"\"Injected synthetic TypeError.\"\"\"
    from src.app import calculate_division
    calculate_division("invalid_string", 5)
""",
    "ValueError": """
def test_value_error():
    \"\"\"Injected synthetic ValueError.\"\"\"
    from src.app import convert_to_int
    convert_to_int("unparseable_alphanumeric_0x99")
""",
    "AttributeError": """
def test_attribute_error():
    \"\"\"Injected synthetic AttributeError.\"\"\"
    from src.app import get_object_attribute
    get_object_attribute(object())
""",
    "ZeroDivisionError": """
def test_zero_division_error():
    \"\"\"Injected synthetic ZeroDivisionError.\"\"\"
    from src.app import calculate_division
    calculate_division(42, 0)
""",
    "FileNotFoundError": """
def test_file_not_found_error():
    \"\"\"Injected synthetic FileNotFoundError.\"\"\"
    from src.app import read_config_file
    read_config_file("fixtures/non_existent_pipeline_config.json")
""",
}

def inject(error_type: str):
    if error_type == "success":
        # For success runs, just use the baseline tests without any mutation
        baseline = TEST_FILE.read_text(encoding="utf-8")
        # Remove any previous mutation
        if "# --- SYNTHETIC F3 FAILURE MUTATION ---" in baseline:
            baseline = baseline.split("# --- SYNTHETIC F3 FAILURE MUTATION ---")[0]
        TEST_FILE.write_text(baseline, encoding="utf-8")
        print(f"[Mutation Injected] Using baseline tests (no mutation) for success run")
        return

    if error_type not in ERROR_MUTATIONS:
        raise ValueError(f"Unknown error type: {error_type}. Valid: {list(ERROR_MUTATIONS.keys())} + ['success']")

    baseline = TEST_FILE.read_text(encoding="utf-8")
    # Remove any previous mutation
    if "# --- SYNTHETIC F3 FAILURE MUTATION ---" in baseline:
        baseline = baseline.split("# --- SYNTHETIC F3 FAILURE MUTATION ---")[0]
    mutation = ERROR_MUTATIONS[error_type]
    mutated_content = f"{baseline}\n\n# --- SYNTHETIC F3 FAILURE MUTATION ---\n{mutation}"
    TEST_FILE.write_text(mutated_content, encoding="utf-8")
    print(f"[Mutation Injected] Successfully injected {error_type} into {TEST_FILE}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inject synthetic test mutation into tests/test_app.py")
    parser.add_argument("--error-type", type=str, required=True, help="Error type to inject")
    args = parser.parse_args()
    inject(args.error_type)
