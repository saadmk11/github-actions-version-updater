import subprocess

import github_action_utils as gha_utils  # type: ignore


def configure_git_author(username: str, email: str) -> None:
    """
    Configure the git author.
    """
    with gha_utils.group("Configure Git Author"):
        gha_utils.notice(f"Setting Git Commit User to '{username}'.")
        gha_utils.notice(f"Setting Git Commit email to '{email}'.")

        run_subprocess_command(["git", "config", "user.name", username])
        run_subprocess_command(["git", "config", "user.email", email])


def create_new_git_branch(base_branch_name: str, new_branch_name: str) -> None:
    """
    Create a new git branch from base branch.
    """
    with gha_utils.group(
        f"Create New Branch ({base_branch_name} -> {new_branch_name})"
    ):
        run_subprocess_command(["git", "checkout", base_branch_name])
        run_subprocess_command(["git", "checkout", "-b", new_branch_name])


def git_commit_changes(
    commit_message: str, commit_author: str, commit_branch_name: str
) -> None:
    """
    Commit the changed files.
    """
    with gha_utils.group("Commit Changes"):
        run_subprocess_command(["git", "add", "."])
        run_subprocess_command(
            ["git", "commit", f"--author={commit_author}", "-m", commit_message]
        )
        run_subprocess_command(["git", "push", "-u", "origin", commit_branch_name])


def git_has_changes() -> bool:
    """
    Check if there are changes to commit.
    """
    try:
        subprocess.check_output(["git", "diff", "--exit-code"])
        return False
    except subprocess.CalledProcessError:
        return True


def git_diff() -> str:
    """Return the git diff"""
    return subprocess.run(["git", "diff"], capture_output=True, text=True).stdout


def run_subprocess_command(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)

    if result.returncode != 0:
        gha_utils.error(result.stderr)
        raise SystemExit(result.returncode)

    gha_utils.echo(result.stdout)
