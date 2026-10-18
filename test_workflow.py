from automation.git_utils import commit_and_push
from automation.workflow_utils import wait_for_run


def main():
    sha = commit_and_push("Workflow detection test")
    print("Commit:", sha)

    workflow = wait_for_run(sha)
    print(workflow)


if __name__ == "__main__":
    main()