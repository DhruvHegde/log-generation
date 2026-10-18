import subprocess
import time


def run(command):
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )

    if result.returncode != 0:
        raise Exception(result.stderr)

    return result.stdout.strip()

def commit_and_push(message):
    print("Adding files...")
    run("git add .")

    print("Committing...")
    run(f'git commit -m "{message}"')

    print("Getting branch...")
    branch = run("git branch --show-current")
    print("Branch:", branch)

    print("Pushing...")
    run(f"git push origin {branch}")

    print("Getting SHA...")
    sha = run("git rev-parse HEAD")

    return sha


def find_commit_by_message(message):
    result = subprocess.run(
        ["git", "log", "-1", "--format=%H", "--fixed-strings", f"--grep={message}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return result.stdout.strip() or None


def create_empty_commit(message):
    tree = run("git rev-parse HEAD^{tree}")
    result = subprocess.run(
        ["git", "commit-tree", tree, "-p", "HEAD", "-m", message],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())

    commit_sha = result.stdout.strip()
    run(f"git update-ref HEAD {commit_sha}")
    return commit_sha


def _commit_is_on_remote(commit_sha, branch):
    run(f'git fetch origin "{branch}"')
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit_sha, "FETCH_HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.strip())
    return result.returncode == 0


def push_commit(commit_sha, max_attempts=3):
    branch = run("git branch --show-current")
    if not branch:
        raise RuntimeError("Cannot push a success run from a detached HEAD.")

    last_error = None
    for attempt in range(max_attempts):
        try:
            run(f'git push origin "{branch}"')
            return
        except Exception as exc:
            last_error = exc
            try:
                if _commit_is_on_remote(commit_sha, branch):
                    return
            except Exception as remote_check_error:
                last_error = remote_check_error

            if attempt + 1 < max_attempts:
                time.sleep(2)

    raise RuntimeError(
        f"Could not confirm that commit {commit_sha} reached origin after "
        f"{max_attempts} push attempts."
    ) from last_error


# def commit_and_push(message):

#     run("git add .")

#     run(f'git commit -m "{message}"')

#     branch = run("git branch --show-current")
#     run(f"git push origin {branch}")

#     sha = run("git rev-parse HEAD")

#     return sha