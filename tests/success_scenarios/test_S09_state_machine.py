"""Scenario S09: Finite state machine transitions and event tracking."""
import pytest


class PipelineStateMachine:
    ALLOWED_TRANSITIONS = {
        "PENDING": {"INITIALIZING", "CANCELLED"},
        "INITIALIZING": {"RUNNING", "FAILED"},
        "RUNNING": {"COMPLETED", "FAILED", "TIMED_OUT"},
        "COMPLETED": set(),
        "FAILED": set(),
        "CANCELLED": set(),
        "TIMED_OUT": set(),
    }

    def __init__(self):
        self.state = "PENDING"
        self.history = ["PENDING"]

    def transition(self, next_state: str):
        allowed = self.ALLOWED_TRANSITIONS.get(self.state, set())
        if next_state not in allowed:
            raise ValueError(
                f"Invalid transition from '{self.state}' to '{next_state}'."
            )
        self.state = next_state
        self.history.append(next_state)

    @property
    def is_terminal(self) -> bool:
        return len(self.ALLOWED_TRANSITIONS.get(self.state, set())) == 0


def test_state_machine_success_path():
    sm = PipelineStateMachine()
    assert sm.state == "PENDING"
    assert not sm.is_terminal

    sm.transition("INITIALIZING")
    assert sm.state == "INITIALIZING"

    sm.transition("RUNNING")
    assert sm.state == "RUNNING"

    sm.transition("COMPLETED")
    assert sm.state == "COMPLETED"
    assert sm.is_terminal
    assert sm.history == ["PENDING", "INITIALIZING", "RUNNING", "COMPLETED"]


def test_invalid_transitions():
    sm = PipelineStateMachine()
    with pytest.raises(ValueError):
        sm.transition("COMPLETED")

    sm.transition("INITIALIZING")
    with pytest.raises(ValueError):
        sm.transition("PENDING")
