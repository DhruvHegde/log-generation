import json
import os

def save_metadata(path, metadata):

    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    # Prevent overwriting an existing metadata file
    if os.path.exists(path):
        raise FileExistsError(f"Metadata already exists: {path}")

    with open(path, "w") as f:
        json.dump(
            metadata,
            f,
            indent=4
        )