import json
import os
import time

STATE_FILE = "state.json"


def load_state(state_file=STATE_FILE):
    """Load state from JSON file.
    
    Args:
        state_file: Path to state file.
        
    Returns:
        dict: Parsed state dictionary.
    """
    with open(state_file, "r") as f:
        return json.load(f)


def save_state(state, state_file=STATE_FILE, max_retries=3, backoff_start=0.1):
    """Save state to JSON file with atomic write and retry on Windows PermissionError.
    
    Writes to a temporary file first, then atomically replaces the target file.
    If replacement fails on Windows (common with file locks), retries with exponential
    backoff before giving up. Always cleans up temp file even if replacement fails.
    
    Args:
        state: Dictionary to save.
        state_file: Path to target state file.
        max_retries: Maximum retry attempts (bounded, default 3).
        backoff_start: Initial backoff in seconds (default 0.1).
        
    Raises:
        OSError: If atomic replacement fails after all retries and other reasons
                 (permissions, disk full, etc.).
        json.JSONEncodeError: If state is not JSON-serializable.
    """
    temporary_file = f"{state_file}.tmp"
    
    try:
        # Write to temporary file (always fresh)
        with open(temporary_file, "w") as f:
            json.dump(state, f, indent=4)
        
        # Attempt atomic replacement with retries on Windows PermissionError
        backoff = backoff_start
        last_error = None
        
        for attempt in range(max_retries):
            try:
                # Atomic replacement: destination must not exist or will be overwritten
                os.replace(temporary_file, state_file)
                return  # Success
            except PermissionError as e:
                # Windows-specific: file may be locked by antivirus, file explorer, etc.
                last_error = e
                if attempt < max_retries - 1:
                    print(f"Warning: state file locked (attempt {attempt + 1}/{max_retries}), "
                          f"retrying in {backoff}s: {e}")
                    time.sleep(backoff)
                    backoff *= 2  # Exponential backoff
                else:
                    # Last attempt failed
                    print(f"Error: Failed to save state after {max_retries} attempts: {e}")
                    raise OSError(
                        f"Failed to save state (Permission denied after {max_retries} retries). "
                        f"File may be locked by another process. Temporary file at {temporary_file}. "
                        f"Original state preserved at {state_file}."
                    ) from e
            except OSError as e:
                # Other OS errors (not PermissionError): disk full, bad path, etc.
                # These are not transient, so raise immediately
                raise OSError(
                    f"Failed to save state (OSError): {e}"
                ) from e
        
        # Should not reach here (loop would raise)
        raise RuntimeError("Unexpected: save_state loop terminated without result")
        
    finally:
        # Always attempt cleanup of temp file, even if replacement succeeded or failed
        # (Successful os.replace() deletes the temp file, but if we failed, it remains)
        try:
            if os.path.exists(temporary_file):
                os.remove(temporary_file)
        except OSError as cleanup_error:
            # Cleanup failure should not mask the original error
            print(f"Warning: Could not clean up temporary file {temporary_file}: {cleanup_error}")
            # Don't raise; we want the original error to propagate if replacement failed
