import subprocess


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
        # Git writes different output to stdout vs stderr depending on the
        # command and failure mode.  For example, "git commit" with nothing
        # to commit returns exit code 1 and puts its message on STDOUT with
        # an empty STDERR.  "git push" authentication failures go to STDERR.
        # Build a useful error message from whichever stream is non-empty.
        stdout_part = result.stdout.strip()
        stderr_part = result.stderr.strip()

        if stderr_part and stdout_part:
            detail = f"stderr: {stderr_part}\nstdout: {stdout_part}"
        elif stderr_part:
            detail = stderr_part
        elif stdout_part:
            detail = stdout_part
        else:
            detail = f"(no output captured)"

        raise Exception(
            f"Git command failed (exit {result.returncode}).\n"
            f"Command: {command}\n"
            f"{detail}"
        )

    return result.stdout.strip()


def commit_and_push(message):
    print("Adding files...")
    run("git add .")

    print("Committing...")
    # "git commit" exits with code 1 and writes to stdout (not stderr) when
    # there is nothing new to stage.  Detect this before calling run() so we
    # can give a clear, actionable error rather than a cryptic blank message.
    status_result = subprocess.run(
        "git status --porcelain",
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )
    if not status_result.stdout.strip():
        raise Exception(
            "Nothing to commit: the working tree is clean after 'git add .'.\n"
            "This usually means app.py was not actually changed relative to HEAD.\n"
            "Check whether the scenario content is identical to the last committed app.py."
        )

    run(f'git commit -m "{message}"')

    print("Getting branch...")
    branch = run("git branch --show-current")
    print("Branch:", branch)

    print("Pushing...")
    run(f"git push origin {branch}")

    print("Getting SHA...")
    sha = run("git rev-parse HEAD")

    return sha


# def commit_and_push(message):

#     run("git add .")

#     run(f'git commit -m "{message}"')

#     branch = run("git branch --show-current")
#     run(f"git push origin {branch}")

#     sha = run("git rev-parse HEAD")

#     return sha