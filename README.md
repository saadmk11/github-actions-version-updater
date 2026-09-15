# GitHub Actions Version Updater

[![GitHub release](https://img.shields.io/github/v/release/saadmk11/github-actions-version-updater?style=flat-square)](https://github.com/saadmk11/github-actions-version-updater/releases/latest)
[![License](https://img.shields.io/github/license/saadmk11/github-actions-version-updater?style=flat-square)](LICENSE)
[![GitHub Marketplace](https://img.shields.io/badge/Get%20It-on%20Marketplace-orange?style=flat-square)](https://github.com/marketplace/actions/github-actions-version-updater)
[![PyPI](https://img.shields.io/pypi/v/update-gha?style=flat-square)](https://pypi.org/project/update-gha/)
[![CI](https://img.shields.io/github/actions/workflow-status/saadmk11/github-actions-version-updater/ci.yaml?label=CI&style=flat-square)](https://github.com/saadmk11/github-actions-version-updater/actions/workflows/ci.yaml)

Scans workflow YAML for `uses:` pins, asks GitHub for a newer release tag, release commit, or default-branch SHA, and rewrites only the version token. Quotes, comments, and line endings stay as they are. Run it as a scheduled Action that opens a pull request, or as the `update-gha` CLI on your machine.

| | [GitHub Action](#github-action) | [Python package](#python-package) |
| --- | --- | --- |
| **Use this when** | You want a scheduled job that opens a pull request | You want a CLI on your machine or in other CI |
| **Add it with** | `uses: saadmk11/github-actions-version-updater@v1.0.0` | `pip install update-gha` or `uvx update-gha` |
| **Pull requests** | Opened by default | Optional (`--pull-request`) |

The Marketplace listing and GitHub repo are **github-actions-version-updater**. The PyPI project is **[update-gha](https://pypi.org/project/update-gha/)**. Same updater, two ways to run it.

## Contents

- [GitHub Action](#github-action)
  - [What it does](#what-it-does)
  - [How the action works](#how-the-action-works)
  - [Quick start](#quick-start)
  - [Version sources](#version-sources)
  - [Release types](#release-types)
  - [Action inputs](#action-inputs)
  - [Action outputs](#action-outputs)
  - [Access token](#access-token)
  - [Example workflows](#example-workflows)
  - [Git LFS](#git-lfs)
  - [Alternative](#alternative)
- [Python package](#python-package)
  - [Install](#install)
  - [How the CLI works](#how-the-cli-works)
  - [Command examples](#command-examples)
  - [Configuration](#configuration)
  - [CLI options](#cli-options)
- [Development](#development)
  - [Prerequisites](#prerequisites)
  - [Setup](#setup)
  - [Layout](#layout)
  - [Tests](#tests)
  - [Lint and types](#lint-and-types)
  - [Pre-commit](#pre-commit)
  - [Run locally](#run-locally)
  - [CI](#ci)
- [License](#license)

---

## GitHub Action

Add a workflow to this repository. On a schedule (or when you run it by hand) the action scans `uses:` pins and opens a pull request with the updates.

[Get it on the Marketplace](https://github.com/marketplace/actions/github-actions-version-updater)

Under the hood it is a composite action: it installs `update-gha[action]` from this checkout into an isolated CPython 3.14 environment and runs `update-gha --pull-request`. It does not change the job's `python` on `PATH`.

v1 is not a Docker image. Self-hosted runners need bash and outbound network so uv can install that isolated interpreter; Docker is not required.

### What it does

Like Dependabot, but only for GitHub Actions:

- Finds `uses:` pins in `.github/workflows` and any extra paths you pass
- Looks up a newer release tag, release commit, or default-branch SHA
- Rewrites **only** the version token — quotes, comments, and line endings stay as they are
- Commits the result and opens a pull request (unless you set `skip_pull_request`)

Local actions (`./path`) and container actions (`docker://…`) are not updated.

![GitHub Actions Version Updater Demo](https://user-images.githubusercontent.com/24854406/113888349-15dbdc00-97e4-11eb-91a6-622828455d1f.gif)

### How the action works

1. Check out the repository with a token that can write workflow files.
2. Scan workflow YAML for `owner/repo@version` pins.
3. Ask the GitHub API for a newer version, unless the pin is listed in `ignore`.
4. Rewrite matching pins in place.
5. Create a branch, push, and open a PR — unless `skip_pull_request` is `true`.

Draft, prerelease, and unpublished GitHub releases are ignored.

### Quick start

Trigger on a [`schedule`](https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#schedule) or [`workflow_dispatch`](https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#workflow_dispatch). Save this as `.github/workflows/updater.yaml`:

```yaml
name: GitHub Actions Version Updater

on:
  workflow_dispatch:
  schedule:
    - cron: "0 0 * * 0"   # every Sunday

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.WORKFLOW_SECRET }}

      - name: Run GitHub Actions Version Updater
        uses: saadmk11/github-actions-version-updater@v1.0.0
        with:
          token: ${{ secrets.WORKFLOW_SECRET }}
```

> [!WARNING]
> `${{ secrets.GITHUB_TOKEN }}` cannot update workflow files. Create a personal access token, store it as a repository secret, and pass that secret as `token` on **both** `actions/checkout` and this action. Details are in [Access token](#access-token).

### Version sources

`update_version_with` chooses what is written back into each `uses:` pin:

| Value | What is written | Example |
| --- | --- | --- |
| `release-tag` (default) | Latest published stable release tag | `actions/checkout@v4.2.2` |
| `release-commit-sha` | Commit that the latest stable tag points at | `actions/checkout@11bd7190…` |
| `default-branch-sha` | Latest commit on the action's default branch | `actions/checkout@11bd7190…` |

### Release types

`release_types` limits which SemVer bumps are applied. It only applies to `release-tag` and `release-commit-sha`.

| Value | Updates when |
| --- | --- |
| `all` (default) | Any newer stable release |
| `major` | The major component increases (`v3` → `v4`) |
| `minor` | Same major, higher minor (`v4.1` → `v4.2`) |
| `patch` | Same major and minor, higher patch (`v4.2.1` → `v4.2.2`) |

You can combine them: `minor, patch`.

Two cases leave a pin unchanged instead of guessing:

- The current pin is not SemVer, and `release_types` is not `all`
- `update_version_with` is `release-commit-sha`, `release_types` is restricted, and the current SHA cannot be matched to a release tag

### Action inputs

| Name | Required | Description | Default |
| --- | --- | --- | --- |
| `token` | Yes | Personal access token that can update workflows. See [Access token](#access-token). | — |
| `committer_username` | No | Git author name on the update commit | `github-actions[bot]` |
| `committer_email` | No | Git author email on the update commit | `github-actions[bot]@users.noreply.github.com` |
| `commit_message` | No | Commit message | `Update GitHub Action Versions` |
| `pull_request_title` | No | Pull request title | `Update GitHub Action Versions` |
| `pull_request_branch` | No | PR head branch. If set, that branch is force-pushed with lease. Cannot be `main`, `master`, or the repository base branch. | generated (`gh-actions-update-<id>`) |
| `ignore` | No | Comma-separated pins to leave unchanged. Must match the `uses` value **exactly**, including the current version (`actions/checkout@v4`). | empty |
| `skip_pull_request` | No | If `true`, write the updates, print a diff, and **fail the job** instead of opening a PR. | `false` |
| `update_version_with` | No | `release-tag`, `release-commit-sha`, or `default-branch-sha` | `release-tag` |
| `release_types` | No | `all`, or any of `major`, `minor`, `patch` | `all` |
| `pull_request_user_reviewers` | No | Comma-separated usernames requested on a **new** PR | empty |
| `pull_request_team_reviewers` | No | Comma-separated team slugs requested on a **new** PR | empty |
| `pull_request_labels` | No | Comma-separated labels added on a **new** PR | empty |
| `extra_workflow_locations` | No | Extra workflow files or directories. Directories are searched recursively. `.github/workflows` is always scanned if it exists. | empty |

Reviewers and labels are applied only when this run **opens a new** pull request. They are skipped if a PR for that branch already exists.

### Action outputs

Set only when this run created a pull request. Empty if you skipped the PR, nothing changed, or a PR for the branch already existed.

| Name | Description |
| --- | --- |
| `GHA_UPDATE_PR_NUMBER` | Number of the pull request this run created |
| `pull-request-number` | Same value |

```yaml
- name: Run GitHub Actions Version Updater
  id: update
  uses: saadmk11/github-actions-version-updater@v1.0.0
  with:
    token: ${{ secrets.WORKFLOW_SECRET }}

- name: Use the pull request number
  if: steps.update.outputs.GHA_UPDATE_PR_NUMBER
  run: echo "Opened PR #${{ steps.update.outputs.GHA_UPDATE_PR_NUMBER }}"
```

### Access token

GitHub's default `${{ secrets.GITHUB_TOKEN }}` cannot push changes to workflow files. Create a [personal access token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens), add it to the repository [Actions secrets](https://docs.github.com/en/actions/security-guides/using-secrets-in-github-actions), and pass that secret as `token`.

**Classic PAT**

- `repo` — push the branch and open the pull request
- `workflow` — update workflow files

**Fine-grained PAT**

- Contents: Read and write
- Workflows: Read and write
- Pull requests: Read and write
- Metadata: Read-only (granted with the permissions above)

Use the **same** secret on `actions/checkout` and on this action so the push uses that credential.

### Example workflows

#### All inputs

```yaml
name: GitHub Actions Version Updater

on:
  workflow_dispatch:
  schedule:
    - cron: "0 0 * * 0"

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.WORKFLOW_SECRET }}

      - name: Run GitHub Actions Version Updater
        uses: saadmk11/github-actions-version-updater@v1.0.0
        with:
          token: ${{ secrets.WORKFLOW_SECRET }}
          committer_username: "actions-bot"
          committer_email: "actions-bot@users.noreply.github.com"
          commit_message: "chore: bump GitHub Actions"
          pull_request_title: "chore: bump GitHub Actions"
          pull_request_branch: "actions-update"
          ignore: "actions/checkout@v4, actions/cache@v4"
          update_version_with: "release-tag"
          release_types: "minor, patch"
          pull_request_user_reviewers: "octocat, hubot"
          pull_request_team_reviewers: "justice-league"
          pull_request_labels: "dependencies, automated"
          extra_workflow_locations: "deploy/workflows, path/to/workflow.yaml"
```

#### Write updates without a pull request

Writes the files, prints a diff, and fails the job if anything changed. Use this when another step or a person should commit.

```yaml
- name: Run GitHub Actions Version Updater
  uses: saadmk11/github-actions-version-updater@v1.0.0
  with:
    token: ${{ secrets.WORKFLOW_SECRET }}
    skip_pull_request: "true"
```

### Git LFS

If the repository uses [Git LFS](https://git-lfs.github.com/), check out with `lfs: false` or remove the LFS hooks before this action runs. Otherwise creating the update branch can fail when the LFS binary is not on the runner.

```yaml
- uses: actions/checkout@v4
  with:
    token: ${{ secrets.WORKFLOW_SECRET }}
    lfs: false

- name: Remove LFS hooks
  run: |
    rm -f .git/hooks/post-checkout .git/hooks/pre-push

- name: Run GitHub Actions Version Updater
  uses: saadmk11/github-actions-version-updater@v1.0.0
  with:
    token: ${{ secrets.WORKFLOW_SECRET }}
```

### Alternative

[Dependabot](https://docs.github.com/en/code-security/dependabot/working-with-dependabot/keeping-your-actions-up-to-date-with-dependabot) can also bump GitHub Actions. Prefer this action when you want SHA pins, default-branch tips, ignore lists that match exact `uses` values, or one scheduled PR with your own title, reviewers, and labels.

---

## Python package

**update-gha** is the CLI the Action runs. Use it locally or in another CI system.

[PyPI](https://pypi.org/project/update-gha/) · [Changelog](CHANGELOG.md) · [Issues](https://github.com/saadmk11/github-actions-version-updater/issues)

- Scans `.github/workflows` plus extra files or directories
- Rewrites only the version token (YAML structure, quotes, comments, and line endings stay)
- Three version sources: release tag, release commit SHA, default-branch SHA
- SemVer filters (`major` / `minor` / `patch`)
- `--check`, `--dry-run`, `--diff`, `--fail-on-update`, and JSON output
- Optional `--pull-request` (install `update-gha[action]`)
- Config from CLI flags, `GHA_UPDATE_*` environment variables, or `[tool.update-gha]` in `pyproject.toml`

### Install

Requires **Python 3.12** or newer.

```bash
# one-off
uvx update-gha --help
pip install update-gha

# in a project
uv add update-gha
uv run update-gha --check

# user-wide tool
uv tool install update-gha
```

Pull-request mode needs GitPython. Install the extra only if you will pass `--pull-request`:

```bash
pip install 'update-gha[action]'
uv add 'update-gha[action]'
uv tool install --with 'update-gha[action]' update-gha
```

### How the CLI works

1. Scan `.github/workflows` (and any extra paths) for `uses:` pins.
2. Ask GitHub for a newer release or commit, unless the pin is ignored.
3. Rewrite only the version token.
4. If you passed `--pull-request` and files were written, commit, push, and open a PR.

| Situation | Token needed? |
| --- | --- |
| Public actions, local rewrite / `--check` / `--dry-run` | No. Passing one avoids the unauthenticated API rate limit. |
| Private action repositories | Yes |
| `--pull-request` | Yes, plus `owner/repo` (`--repository` or `GITHUB_REPOSITORY`) |

### Command examples

```bash
update-gha                          # rewrite workflow files in place
update-gha --check                  # do not write; exit 1 if any pin would change
update-gha --dry-run --diff         # do not write; print the plan and a unified diff
update-gha --fail-on-update         # write, then exit 1 if anything was written
update-gha --format json
update-gha --ignore 'actions/checkout@v4'
update-gha --update-version-with release-tag --release-types 'minor,patch'
update-gha path/to/extra.yaml
```

Open a pull request (needs `update-gha[action]`):

```bash
export GITHUB_TOKEN=...
export GITHUB_REPOSITORY=owner/repo
update-gha --pull-request
```

`--token` and `--repository` work instead of those environment variables. Tracked files must be clean so the commit contains only updater changes; untracked files are left alone.

### Configuration

Read in this order (later sources lose to earlier ones):

1. CLI flags
2. Environment variables (`GHA_UPDATE_*`, plus `GITHUB_TOKEN` / `GITHUB_REPOSITORY`)
3. `[tool.update-gha]` in the nearest `pyproject.toml` (walks up from the current directory)
4. Built-in defaults

```bash
export GITHUB_TOKEN=...
export GHA_UPDATE_IGNORE_ACTIONS='actions/checkout@v4'
export GHA_UPDATE_UPDATE_VERSION_WITH=release-tag
export GHA_UPDATE_RELEASE_TYPES='minor,patch'
update-gha
```

```toml
[tool.update-gha]
ignore_actions = ["actions/checkout@v4"]
update_version_with = "release-tag"
release_types = ["minor", "patch"]
extra_workflow_locations = ["deploy/workflows"]
committer_username = "bot"
pull_request_title = "Update GitHub Action versions"
```

You can also enable pull-request mode with `GHA_UPDATE_CREATE_PULL_REQUEST=true`. Commit and PR fields (`committer_*`, `pull_request_*`, reviewers, labels) are ignored unless that flag or environment variable is on.

### CLI options

| Option | Purpose | Default |
| --- | --- | --- |
| `--token` | GitHub token. Required for `--pull-request` and private action repos; optional for public lookups. Also `GITHUB_TOKEN` / `GHA_UPDATE_TOKEN`. | unset |
| `--ignore` | Comma-separated exact `uses` pins to skip, including the current version. | empty |
| `--update-version-with` | `release-tag`, `release-commit-sha`, or `default-branch-sha`. | `release-tag` |
| `--release-types` | `major`, `minor`, `patch`, or `all`. No effect on `default-branch-sha`. | `all` |
| `--extra-workflow-locations` | Extra files or directories, comma-separated. Directories are recursive. | empty |
| `PATHS` | Extra files or directories as positional arguments. Same role as `--extra-workflow-locations`. | none |
| `--check` | Do not write. Exit 1 if any pin would change. | off |
| `--dry-run` | Do not write. Exit 0 even if updates exist. | off |
| `--diff` | Print a unified diff. Works with write, `--check`, and `--dry-run`. | off |
| `--fail-on-update` | Write, then exit 1 if any file was written. Incompatible with `--pull-request`, `--check`, and `--dry-run`. | off |
| `--format` | `text` or `json`. JSON sends logs to stderr. | `text` |
| `--verbose` / `--quiet` | Debug logs, or warnings and errors only. Mutually exclusive. | off |
| `--pull-request` | Commit, push, and open a PR. Needs `update-gha[action]`, `--token`, `--repository`, and a clean tracked tree. | off |
| `--repository` | `owner/repo` that receives the PR. Also `GITHUB_REPOSITORY`. Unused for a local rewrite. | unset |
| `--committer-username` | Git author name for the PR commit. | `github-actions[bot]` |
| `--committer-email` | Git author email for the PR commit. | `github-actions[bot]@users.noreply.github.com` |
| `--commit-message` | Message for the PR commit. | `Update GitHub Action Versions` |
| `--pull-request-title` | Title of the pull request. | `Update GitHub Action Versions` |
| `--pull-request-branch` | Head branch. Omit for a unique name; a given name is force-pushed. Cannot be the base branch. | generated (`gh-actions-update-<id>`) |
| `--pull-request-reviewers` | Usernames requested on a **new** PR, comma-separated. | empty |
| `--pull-request-teams` | Team slugs requested on a **new** PR, comma-separated. | empty |
| `--pull-request-labels` | Labels added on a **new** PR, comma-separated. | empty |

See `update-gha --help` for the full text.

---

## Development

The package lives in `src/update_gha`. Tests are in `tests/`. Tooling is configured in `pyproject.toml` and run with [uv](https://docs.astral.sh/uv/) (0.11.32 or newer).

### Prerequisites

- Python **3.12+** (CI covers 3.12, 3.13, and 3.14; `.python-version` is `3.14`)
- [uv](https://docs.astral.sh/uv/) **0.11.32** or newer

### Setup

```bash
git clone https://github.com/saadmk11/github-actions-version-updater.git
cd github-actions-version-updater
uv sync --all-groups --all-extras
```

That installs the package (editable), the `[action]` extra (GitPython), and the `dev` group (pytest, ruff, mypy).

### Layout

| Path | Role |
| --- | --- |
| `src/update_gha/` | Core package: scan, rewrite, GitHub lookup, config, models |
| `src/update_gha/cli/` | `update-gha` console script |
| `src/update_gha/action/` | Git + pull-request helpers (optional extra) |
| `tests/` | Pytest suite; `tests/fixtures/` are YAML rewrite pairs |
| `action.yaml` | Composite GitHub Action that runs this checkout |
| `.github/workflows/ci.yaml` | Lint and test matrix |

### Tests

```bash
uv run pytest
```

Coverage is required at **100%** (`--cov-fail-under=100`). Tests do not hit the live GitHub API; HTTP and git are faked.

```bash
uv run pytest tests/test_rewrite.py          # one file
uv run pytest tests/test_cli.py::test_help   # one test
```

`tests/smoke_test.py` is also run by the release workflow against the built wheel and sdist.

### Lint and types

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

Ruff uses a line length of 88. mypy runs in strict mode on `src` and `tests`.

To apply fixes:

```bash
uv run ruff check --fix .
uv run ruff format .
```

### Pre-commit

[`.pre-commit-config.yaml`](.pre-commit-config.yaml) runs end-of-file / whitespace checks, Ruff, and mypy. The Ruff and mypy hooks call `uv run`, so finish **Setup** first. Install [pre-commit](https://pre-commit.com/) separately (it is not in the `dev` group):

```bash
uv tool install pre-commit
pre-commit install
pre-commit run --all-files
```

### Run locally

```bash
uv run update-gha --help
uv run update-gha --dry-run --diff
uv run python -m update_gha --check
```

### CI

[`.github/workflows/ci.yaml`](.github/workflows/ci.yaml) runs on pushes and pull requests to `main`:

- **lint** — `ruff check`, `ruff format --check`, `mypy` on Python 3.14
- **test** — `pytest` on Python 3.12, 3.13, and 3.14

Python dependencies are updated by Dependabot (`uv`). Action pins in this repository are updated by [`.github/workflows/update-actions.yaml`](.github/workflows/update-actions.yaml).

## License

Released under the [MIT License](LICENSE).
