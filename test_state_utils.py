"""Tests for state_utils with Windows PermissionError recovery."""

import json
import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import time

from automation.state_utils import save_state, load_state


class TestSaveStateSuccess:
    """Test successful state saves."""
    
    def test_save_state_creates_valid_json(self, tmp_path):
        """Successful save creates valid JSON file."""
        state_file = tmp_path / "state.json"
        state = {"count": 10, "name": "test"}
        
        save_state(state, str(state_file))
        
        # Verify file exists and contains correct state
        assert state_file.exists()
        with open(state_file) as f:
            loaded = json.load(f)
        assert loaded == state
    
    def test_save_state_overwrites_existing_file(self, tmp_path):
        """Saving overwrites existing state file."""
        state_file = tmp_path / "state.json"
        
        # Write initial state
        initial = {"version": 1}
        save_state(initial, str(state_file))
        
        # Overwrite with new state
        updated = {"version": 2, "data": "new"}
        save_state(updated, str(state_file))
        
        # Verify new state is present
        with open(state_file) as f:
            loaded = json.load(f)
        assert loaded == updated
        assert loaded["version"] == 2
    
    def test_save_state_cleans_up_temp_file_on_success(self, tmp_path):
        """Temp file is removed after successful save."""
        state_file = tmp_path / "state.json"
        temp_file = Path(f"{state_file}.tmp")
        state = {"test": "data"}
        
        save_state(state, str(state_file))
        
        # Verify state file exists
        assert state_file.exists()
        # Verify temp file does not exist
        assert not temp_file.exists()


class TestSaveStateTransientFailure:
    """Test handling of transient PermissionError during replacement."""
    
    def test_save_state_retries_on_permission_error_then_succeeds(self, tmp_path):
        """Transient PermissionError on os.replace is retried and succeeds."""
        state_file = tmp_path / "state.json"
        state = {"count": 42}
        
        call_count = [0]
        original_replace = os.replace
        
        def mock_replace(src, dst):
            call_count[0] += 1
            if call_count[0] < 2:
                # First call fails
                raise PermissionError("[WinError 5] Access is denied")
            # Second call succeeds
            return original_replace(src, dst)
        
        with patch('automation.state_utils.os.replace', side_effect=mock_replace):
            with patch('automation.state_utils.time.sleep'):
                save_state(state, str(state_file))
        
        # Verify retried and succeeded
        assert call_count[0] == 2
        with open(state_file) as f:
            loaded = json.load(f)
        assert loaded == state
    
    def test_save_state_retries_with_exponential_backoff(self, tmp_path):
        """PermissionError retries use exponential backoff."""
        state_file = tmp_path / "state.json"
        state = {"data": "value"}
        
        sleep_times = []
        
        def mock_replace(src, dst):
            raise PermissionError("Access denied")
        
        def mock_sleep(duration):
            sleep_times.append(duration)
        
        with patch('automation.state_utils.os.replace', side_effect=mock_replace):
            with patch('automation.state_utils.time.sleep', side_effect=mock_sleep):
                with pytest.raises(OSError) as exc_info:
                    save_state(state, str(state_file), max_retries=3, backoff_start=0.1)
        
        # Verify exponential backoff progression
        assert sleep_times == [0.1, 0.2]  # max_retries=3 means 2 sleeps
        assert "Permission denied" in str(exc_info.value)
    
    def test_save_state_fails_after_max_retries_exhausted(self, tmp_path):
        """Transient failures exhausted retries raise OSError."""
        state_file = tmp_path / "state.json"
        state = {"attempt": "failed"}
        
        call_count = [0]
        
        def mock_replace(src, dst):
            call_count[0] += 1
            raise PermissionError(f"[WinError 5] Access denied (attempt {call_count[0]})")
        
        with patch('automation.state_utils.os.replace', side_effect=mock_replace):
            with patch('automation.state_utils.time.sleep'):
                with pytest.raises(OSError) as exc_info:
                    save_state(state, str(state_file), max_retries=2)
        
        # Verify all retries were attempted
        assert call_count[0] == 2
        # Verify error message is informative
        assert "Permission denied" in str(exc_info.value)
        assert "retries" in str(exc_info.value)
    
    def test_save_state_preserves_original_on_failure(self, tmp_path):
        """Original state file is preserved even if replacement fails."""
        state_file = tmp_path / "state.json"
        original_state = {"version": 1, "status": "original"}
        
        # Create original file
        with open(state_file, "w") as f:
            json.dump(original_state, f)
        
        new_state = {"version": 2, "status": "new"}
        
        def mock_replace(src, dst):
            raise PermissionError("File locked")
        
        with patch('automation.state_utils.os.replace', side_effect=mock_replace):
            with patch('automation.state_utils.time.sleep'):
                with pytest.raises(OSError):
                    save_state(new_state, str(state_file), max_retries=2)
        
        # Verify original state is still present
        with open(state_file) as f:
            loaded = json.load(f)
        assert loaded == original_state
        assert loaded["status"] == "original"
    
    def test_save_state_cleans_up_temp_file_on_failure(self, tmp_path):
        """Temp file is cleaned up even if replacement fails."""
        state_file = tmp_path / "state.json"
        temp_file = Path(f"{state_file}.tmp")
        state = {"cleanup": "test"}
        
        # Create original file
        with open(state_file, "w") as f:
            json.dump({"original": True}, f)
        
        def mock_replace(src, dst):
            raise PermissionError("Access denied")
        
        with patch('automation.state_utils.os.replace', side_effect=mock_replace):
            with patch('automation.state_utils.time.sleep'):
                with pytest.raises(OSError):
                    save_state(state, str(state_file), max_retries=2)
        
        # Verify temp file was cleaned up
        assert not temp_file.exists()
        # Verify original still exists
        assert state_file.exists()


class TestSaveStateOtherErrors:
    """Test handling of non-transient OS errors."""
    
    def test_save_state_raises_immediately_on_non_permission_error(self, tmp_path):
        """Non-PermissionError OSErrors are raised immediately (no retry)."""
        state_file = tmp_path / "state.json"
        state = {"data": "test"}
        
        call_count = [0]
        
        def mock_replace(src, dst):
            call_count[0] += 1
            raise OSError("Disk full")
        
        with patch('automation.state_utils.os.replace', side_effect=mock_replace):
            with pytest.raises(OSError) as exc_info:
                save_state(state, str(state_file), max_retries=3)
        
        # Should fail immediately, no retries
        assert call_count[0] == 1
        assert "Disk full" in str(exc_info.value)
    
    def test_save_state_handles_json_encode_error(self, tmp_path):
        """Non-serializable state raises JSONEncodeError."""
        state_file = tmp_path / "state.json"
        
        # Create state with non-serializable object
        class NonSerializable:
            pass
        
        state = {"obj": NonSerializable()}
        
        with pytest.raises(TypeError):  # json.dump raises TypeError for non-serializable
            save_state(state, str(state_file))


class TestLoadState:
    """Test load_state function."""
    
    def test_load_state_reads_valid_json(self, tmp_path):
        """load_state reads and parses JSON file correctly."""
        state_file = tmp_path / "state.json"
        original = {
            "accepted_count": 48,
            "attempt_count": 51,
            "pending": {
                "run_number": 49,
                "commit_sha": "abc123",
                "workflow": None
            }
        }
        
        with open(state_file, "w") as f:
            json.dump(original, f)
        
        loaded = load_state(str(state_file))
        
        assert loaded == original
        assert loaded["accepted_count"] == 48


class TestRecoveryScenario:
    """Integration tests for recovery after failed saves."""
    
    def test_recovery_after_permission_error_preserves_data(self, tmp_path):
        """Attempting to save with locked file preserves original; retry succeeds."""
        state_file = tmp_path / "state.json"
        temp_file = Path(f"{state_file}.tmp")
        
        # Initial state
        state_v1 = {"version": 1, "run": 10}
        save_state(state_v1, str(state_file))
        
        # Try to update but simulate file lock
        state_v2 = {"version": 2, "run": 11}
        
        call_count = [0]
        original_replace = os.replace
        
        def mock_replace_first_fail(src, dst):
            call_count[0] += 1
            if call_count[0] == 1:
                raise PermissionError("File locked")
            return original_replace(src, dst)
        
        with patch('automation.state_utils.os.replace', side_effect=mock_replace_first_fail):
            with patch('automation.state_utils.time.sleep'):
                save_state(state_v2, str(state_file))
        
        # Verify new state was saved
        with open(state_file) as f:
            loaded = json.load(f)
        assert loaded["version"] == 2
        assert loaded["run"] == 11
        
        # Verify temp file cleaned up
        assert not temp_file.exists()


class TestConcurrency:
    """Test potential concurrency issues."""
    
    def test_save_state_atomic_prevents_partial_writes(self, tmp_path):
        """State is saved atomically, preventing partial file writes."""
        state_file = tmp_path / "state.json"
        state = {
            "accepted_count": 100,
            "attempt_count": 100,
            "data": "x" * 1000  # Large data to ensure multiple writes
        }
        
        # Save should use atomic os.replace internally
        save_state(state, str(state_file))
        
        # Verify file is valid JSON (not corrupted by interrupted write)
        with open(state_file) as f:
            loaded = json.load(f)
        assert loaded == state
