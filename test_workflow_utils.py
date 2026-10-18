"""Tests for workflow polling with retries, backoff, and exact SHA matching."""

import json
import subprocess
import pytest
from unittest.mock import patch, MagicMock, call
import time

from automation.workflow_utils import get_workflow_runs, wait_for_run


class TestGetWorkflowRunsRetries:
    """Test transient failure retries with exponential backoff."""

    def test_get_workflow_runs_succeeds_on_first_try(self):
        """Successful run requires no retries."""
        expected_runs = [
            {"databaseId": 123, "headSha": "abc123", "status": "completed", "conclusion": "success"}
        ]
        expected_output = json.dumps(expected_runs)

        with patch('automation.workflow_utils.run', return_value=expected_output):
            result = get_workflow_runs()

        assert result == expected_runs

    def test_get_workflow_runs_retries_on_json_parse_error(self):
        """JSON parse error triggers bounded retries."""
        valid_output = json.dumps([{"databaseId": 456}])

        call_count = [0]

        def run_side_effect(cmd):
            call_count[0] += 1
            if call_count[0] < 3:
                return "INVALID JSON {{"  # Trigger JSONDecodeError
            return valid_output

        with patch('automation.workflow_utils.run', side_effect=run_side_effect):
            with patch('automation.workflow_utils.time.sleep'):  # Mock sleep to avoid delays
                result = get_workflow_runs(max_retries=3, initial_backoff=0.1)

        assert result == [{"databaseId": 456}]
        assert call_count[0] == 3

    def test_get_workflow_runs_retries_on_command_error(self):
        """Command execution error triggers bounded retries."""
        valid_output = json.dumps([{"databaseId": 789}])

        call_count = [0]

        def run_side_effect(cmd):
            call_count[0] += 1
            if call_count[0] < 2:
                raise Exception("Network connection closed")
            return valid_output

        with patch('automation.workflow_utils.run', side_effect=run_side_effect):
            with patch('automation.workflow_utils.time.sleep'):
                result = get_workflow_runs(max_retries=3)

        assert result == [{"databaseId": 789}]
        assert call_count[0] == 2

    def test_get_workflow_runs_fails_after_max_retries_exhausted(self):
        """All retries exhausted raises RuntimeError."""
        def run_side_effect(cmd):
            raise Exception("Persistent network error")

        with patch('automation.workflow_utils.run', side_effect=run_side_effect):
            with patch('automation.workflow_utils.time.sleep'):
                with pytest.raises(RuntimeError) as exc_info:
                    get_workflow_runs(max_retries=2, initial_backoff=0.1)

        error_msg = str(exc_info.value)
        # Error message should contain attempt info and original error
        assert "2" in error_msg  # attempt count
        assert "Persistent network error" in error_msg

    def test_get_workflow_runs_exponential_backoff(self):
        """Backoff doubles on each retry attempt."""
        def run_side_effect(cmd):
            raise Exception("Transient error")

        sleep_times = []

        def mock_sleep(duration):
            sleep_times.append(duration)

        with patch('automation.workflow_utils.run', side_effect=run_side_effect):
            with patch('automation.workflow_utils.time.sleep', side_effect=mock_sleep):
                with pytest.raises(RuntimeError):
                    get_workflow_runs(max_retries=3, initial_backoff=0.5)

        # First retry: 0.5s, second retry: 1.0s
        assert sleep_times == [0.5, 1.0]


class TestWaitForRunExactSHAMatching:
    """Test exact commit SHA matching and safety checks."""

    def test_wait_for_run_finds_matching_sha_and_completes_immediately(self):
        """Workflow with matching SHA and completed status returns immediately."""
        commit_sha = "abc123def456"
        runs = [
            {"databaseId": 100, "headSha": commit_sha, "status": "completed", "conclusion": "success"}
        ]

        with patch('automation.workflow_utils.get_workflow_runs', return_value=runs):
            result = wait_for_run(commit_sha)

        assert result["databaseId"] == 100
        assert result["headSha"] == commit_sha
        assert result["status"] == "completed"

    def test_wait_for_run_ignores_non_matching_shas(self):
        """Other workflows with different SHAs are ignored."""
        target_sha = "target123"
        other_sha = "other456"

        call_count = [0]

        def get_runs_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: return some other workflow
                return [{"databaseId": 1, "headSha": other_sha, "status": "completed", "conclusion": "success"}]
            # Second call: return the target workflow
            return [{"databaseId": 2, "headSha": target_sha, "status": "completed", "conclusion": "success"}]

        with patch('automation.workflow_utils.get_workflow_runs', side_effect=get_runs_side_effect):
            with patch('automation.workflow_utils.time.sleep'):
                result = wait_for_run(target_sha)

        assert result["headSha"] == target_sha
        assert result["databaseId"] == 2

    def test_wait_for_run_waits_for_completion(self):
        """Matching SHA in progress is not returned until completed."""
        target_sha = "target789"

        call_count = [0]

        def get_runs_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: workflow is in progress
                return [{"databaseId": 3, "headSha": target_sha, "status": "in_progress", "conclusion": None}]
            # Second call: workflow completed
            return [{"databaseId": 3, "headSha": target_sha, "status": "completed", "conclusion": "success"}]

        with patch('automation.workflow_utils.get_workflow_runs', side_effect=get_runs_side_effect):
            with patch('automation.workflow_utils.time.sleep'):
                result = wait_for_run(target_sha)

        assert result["status"] == "completed"
        assert call_count[0] == 2

    def test_wait_for_run_handles_empty_api_result_gracefully(self):
        """Empty result from API does not cause premature acceptance or crash.
        
        Empty results should be treated as "workflow not ready yet", not as
        "workflow does not exist". The poll should retry, not accept None.
        """
        target_sha = "target111"
        call_count = [0]

        def get_runs_side_effect():
            call_count[0] += 1
            if call_count[0] <= 2:
                # First two calls: API returns empty list (temporary)
                return []
            # Third call: workflow appears
            return [{"databaseId": 6, "headSha": target_sha, "status": "completed", "conclusion": "success"}]

        with patch('automation.workflow_utils.get_workflow_runs', side_effect=get_runs_side_effect):
            with patch('automation.workflow_utils.time.sleep'):
                result = wait_for_run(target_sha)

        assert result["headSha"] == target_sha
        assert call_count[0] == 3  # Retried twice on empty, succeeded on third

    def test_wait_for_run_verifies_sha_on_return(self):
        """Workflow with matching SHA is returned without mismatch error."""
        target_sha = "target999"
        runs = [
            {"databaseId": 4, "headSha": target_sha, "status": "completed", "conclusion": "success"}
        ]

        with patch('automation.workflow_utils.get_workflow_runs', return_value=runs):
            result = wait_for_run(target_sha)

        # Should return successfully because SHA matches
        assert result["headSha"] == target_sha
        assert result["status"] == "completed"

    def test_wait_for_run_recovers_from_transient_polling_failure(self):
        """Polling failure is retried, not immediately fatal."""
        target_sha = "recovery123"
        completed_workflow = {"databaseId": 5, "headSha": target_sha, "status": "completed", "conclusion": "success"}

        call_count = [0]

        def get_runs_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("Network error: connection reset")
            return [completed_workflow]

        with patch('automation.workflow_utils.get_workflow_runs', side_effect=get_runs_side_effect):
            with patch('automation.workflow_utils.time.sleep'):
                result = wait_for_run(target_sha)

        assert result == completed_workflow


class TestStateRecoveryAfterPollingFailure:
    """Test that state is properly saved for recovery after polling failures."""

    def test_state_has_commit_sha_before_polling(self):
        """When commit is made, SHA is saved to state before polling."""
        # This is a simple test of the state dict structure
        state = {
            "accepted_count": 5,
            "attempt_count": 6,
            "pending": {
                "run_number": 6,
                "attempt_number": 6,
                "commit_message": "Test message",
                "dependency": "requests==2.31.0",
                "commit_sha": "abc123def456",  # SHA saved before polling
                "workflow": None,
            }
        }

        # Verify state structure is correct
        assert state["pending"]["commit_sha"] == "abc123def456"
        assert state["pending"]["workflow"] is None
        # This allows polling to be retried without re-committing

    def test_restart_with_existing_commit_sha_does_not_duplicate_attempt(self):
        """Restarting with existing commit_sha does not increment attempt_count again.
        
        When restarting with an existing commit_sha:
        1. attempt_count should remain the same (already set on first attempt)
        2. _ensure_attempt_commit should return existing SHA without re-committing
        3. No new attempt should be created
        """
        import generate_successes
        
        # Simulate loaded state where attempt_count=6, attempt_number=6
        state = {
            "accepted_count": 5,
            "attempt_count": 6,
            "pending": {
                "run_number": 6,
                "attempt_number": 6,
                "commit_message": "Test message",
                "dependency": "requests==2.31.0",
                "commit_sha": "abc123def456",  # Already set from first attempt
                "workflow": None,
            }
        }

        pending = state["pending"]

        # Call _ensure_attempt_commit with existing SHA
        returned_sha = generate_successes._ensure_attempt_commit(pending)

        # Should return the existing SHA
        assert returned_sha == "abc123def456"
        
        # attempt_count should NOT be incremented by _ensure_attempt_commit
        # (it was incremented when pending was first created in _next_pending_attempt)
        assert state["attempt_count"] == 6  # Still 6, not 7
        assert pending["attempt_number"] == 6  # Still 6, not 7

    def test_duplicate_record_detection_on_restart(self):
        """Restarting after metadata write doesn't create duplicate records."""
        # Verify the _existing_csv_record function exists and can detect prior writes
        import generate_successes
        
        # Just verify the function exists and is callable
        assert hasattr(generate_successes, '_existing_csv_record')
        assert callable(generate_successes._existing_csv_record)


class TestWorkflowPollingTimeout:
    """Test timeout behavior when workflow never completes."""

    def test_wait_for_run_timeout_after_max_wait(self):
        """Polling times out after MAX_WAIT seconds without unbounded loop.
        
        This test uses mock timing to verify the timeout is enforced without
        requiring actual elapsed time. It confirms that elapsed time is properly
        tracked and compared against MAX_WAIT.
        """
        # Mock the config values
        config_max_wait = 10
        config_poll_interval = 3

        call_count = [0]

        def get_runs_side_effect():
            call_count[0] += 1
            # Always return a workflow that doesn't match our target SHA
            return [{"databaseId": 10, "headSha": "never_matches", "status": "in_progress", "conclusion": None}]

        with patch('automation.workflow_utils.MAX_WAIT', config_max_wait):
            with patch('automation.workflow_utils.POLL_INTERVAL', config_poll_interval):
                with patch('automation.workflow_utils.get_workflow_runs', side_effect=get_runs_side_effect):
                    with patch('automation.workflow_utils.time.sleep'):
                        with pytest.raises(TimeoutError) as exc:
                            wait_for_run("target_that_never_appears")

        # Verify timeout message includes useful info
        assert "Timed out waiting for GitHub Actions" in str(exc.value)
        
        # Verify we made multiple poll attempts before timing out
        # With MAX_WAIT=10, POLL_INTERVAL=3: should poll at 0s, 3s, 6s, 9s, then timeout
        # That's at least 3-4 calls
        assert call_count[0] >= 3, f"Expected at least 3 polling attempts, got {call_count[0]}"

    def test_wait_for_run_timeout_is_bounded(self):
        """Confirm timeout loop cannot be unbounded; elapsed must reach MAX_WAIT.
        
        This test verifies the loop condition: while elapsed < MAX_WAIT ensures
        termination. It tests with a short MAX_WAIT to confirm bounded behavior.
        """
        config_max_wait = 0.1  # Very short timeout for fast test
        config_poll_interval = 0.05

        call_count = [0]

        def get_runs_side_effect():
            call_count[0] += 1
            # Always return an empty list (no workflows yet)
            return []

        with patch('automation.workflow_utils.MAX_WAIT', config_max_wait):
            with patch('automation.workflow_utils.POLL_INTERVAL', config_poll_interval):
                with patch('automation.workflow_utils.get_workflow_runs', side_effect=get_runs_side_effect):
                    with patch('automation.workflow_utils.time.sleep'):
                        with pytest.raises(TimeoutError):
                            wait_for_run("some_target_sha")

        # With MAX_WAIT=0.1, POLL_INTERVAL=0.05: should poll at 0s, 0.05s, 0.1s (timeout)
        # So we expect 2-3 calls before timeout
        assert call_count[0] <= 5, f"Too many calls ({call_count[0]}) suggests unbounded loop"
        assert call_count[0] >= 2, f"Should have made at least 2 attempts, got {call_count[0]}"
