import json
import os

STATE_FILE = "state.json"


def load_state(state_file=STATE_FILE):
    with open(state_file, "r") as f:
        return json.load(f)


def save_state(state, state_file=STATE_FILE):
    temporary_file = f"{state_file}.tmp"
    with open(temporary_file, "w") as f:
        json.dump(state, f, indent=4)
    os.replace(temporary_file, state_file)