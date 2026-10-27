# GitHub Actions Version Updater

[![GitHub release](https://img.shields.io/github/v/release/saadmk11/github-actions-version-updater?style=flat-square)](https://github.com/saadmk11/github-actions-version-updater/releases/latest)
[![License](https://img.shields.io/github/license/saadmk11/github-actions-version-updater?style=flat-square)](LICENSE)
[![GitHub Marketplace](https://img.shields.io/badge/Get%20It-on%20Marketplace-orange?style=flat-square)](https://github.com/marketplace/actions/github-actions-version-updater)
[![PyPI](https://img.shields.io/pypi/v/update-gha?style=flat-square)](https://pypi.org/project/update-gha/)

Update GitHub Action pins in workflow YAML to a release tag, a release commit SHA, or the default-branch SHA. Run the GitHub Action to open pull requests automatically, or use the `update-gha` CLI to check and update files locally.

| | [GitHub Action](#github-action) | [Python package](#python-package) |
| --- | --- | --- |
| **Use this when** | You want a scheduled job that opens a pull request | You want a CLI on your machine or in other CI |
| **Add it with** | `uses: saadmk11/github-actions-version-updater@v1.0.3` | `pip install update-gha` or `uvx update-gha` |
| **Pull requests** | Opened by default | Optional (`--pull-request`) |

The GitHub repository and Marketplace listing are **github-actions-version-updater**. The Python package and CLI are **[update-gha](https://pypi.org/project/update-gha/)**.

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
  - [Release](#release)
  - [CI](#ci)
- [License](#license)

---

## GitHub Action

Add a workflow to the repository you want to update. The action scans `uses:` pins and opens a pull request with the updates.

[Get it on the Marketplace](https://github.com/marketplace/actions/github-actions-version-updater)

The action installs `update-gha[action]==1.0.3` from PyPI in an isolated CPython 3.14 environment and runs `update-gha --pull-request`. It ignores the consuming repository's Python environment and package-index settings.

Self-hosted runners need Bash, Git, outbound network access, and an Actions runner that supports [Node 24 actions](https://github.com/actions/checkout#checkout-v5). Python is installed automatically.

### What it does

The action:

- Finds `uses:` pins in `.github/workflows` and any extra paths you pass
- Looks up a newer release tag, release commit, or default-branch SHA
- Updates `uses:` pins while preserving YAML formatting, custom comments, and line endings
- When pinning a release commit SHA, adds or updates a `# tag` comment so the diff shows a human-readable version
- Commits the result and opens a pull request (unless you set `skip_pull_request`)

Local actions (`./path`) and container actions (`docker://…`) are not updated.

![GitHub Actions Version Updater Demo](https://user-images.githubusercontent.com/24854406/113888349-15dbdc00-97e4-11eb-91a6-622828455d1f.gif)

### How the action works

1. Check out the repository with a token that can write workflow files.
2. Scan workflow YAML for `owner/repo@version` pins.
3. Ask the GitHub API for a newer version, unless the pin is listed in `ignore`.
4. Rewrite matching pins in place.
5. Create a branch, push, and open a PR — unless `skip_pull_request` is `true`.

The two release modes use published GitHub Releases, excluding drafts and entries marked as prereleases. `default-branch-sha` follows the default branch regardless of releases.

### Quick start

Trigger on a [`schedule`](https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#schedule) or [`workflow_dispatch`](https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#workflow_dispatch). Save this as `.github/workflows/updater.yaml`:

```yaml
name: GitHub Actions Version Updater

on:
  workflow_dispatch:
  schedule:
    - cron: "0 0 * * 0"   # Sunday at 00:00 UTC

permissions:
  contents: read

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          token: ${{ secrets.WORKFLOW_SECRET }}

      - name: Run GitHub Actions Version Updater
        uses: saadmk11/github-actions-version-updater@v1.0.3
        with:
          token: ${{ secrets.WORKFLOW_SECRET }}
```

> [!WARNING]
> `${{ secrets.GITHUB_TOKEN }}` cannot update workflow files. Create a personal access token, store it as a repository secret, and pass it as `token` on both `actions/checkout` and this action. Details are in [Access token](#access-token).

### Version sources

`update_version_with` chooses what is written back into each `uses:` pin:

| Value | What is written | Example |
| --- | --- | --- |
| `release-tag` (default) | Latest eligible published release tag | `actions/checkout@v7.0.1` |
| `release-commit-sha` | Release tag's full commit SHA, plus a `# tag` comment where possible | `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7.0.1` |
| `default-branch-sha` | Latest commit on the action's default branch | `actions/checkout@<default-branch-sha>` |

In `release-commit-sha` mode, tag comments make SHA updates readable. Comments that contain only a version are updated; custom comments such as `# pin for security` are preserved. New tag comments use two spaces before `#`. Multiline scalars and entries followed by other YAML tokens on the same line are not annotated.

The current pin can be a tag, branch, or full commit SHA. The selected mode controls the target independently.

### Release types

`release_types` limits which SemVer bumps are applied. It only applies to `release-tag` and `release-commit-sha`.

| Value | Updates when |
| --- | --- |
| `all` (default) | Any stable release, regardless of bump type |
| `major` | The major component increases (`v1.2.3` → `v2.0.0`) |
| `minor` | Same major, higher minor (`v1.2.3` → `v1.3.0`) |
| `patch` | Same major and minor, higher patch (`v1.2.3` → `v1.2.4`) |

You can combine them: `minor, patch`.

Both release modes use the same current version for filtering. Full versions such as `v1.2.3` are used directly, even without a GitHub Release entry. Branches, SHAs, and moving tags such as `v1` or `v1.2` are matched through their commit to a published release with a full version.

Two cases leave a pin unchanged instead of guessing:

- A restricted filter is requested, but the current pin has no full version and cannot be matched to a release with one.
- No published release is eligible under the selected filter.

With `all`, a branch or SHA can select the latest release without matching a current release version. Switching between a tag and its SHA is still allowed when that release is already current. `default-branch-sha` ignores release-type filters.

### Action inputs

| Name | Required | Description | Default |
| --- | --- | --- | --- |
| `token` | Yes | Personal access token that can update workflows. See [Access token](#access-token). | — |
| `committer_username` | No | Git author and committer name on the update commit | `github-actions[bot]` |
| `committer_email` | No | Git author and committer email on the update commit | `github-actions[bot]@users.noreply.github.com` |
| `commit_message` | No | Commit message | `Update GitHub Action Versions` |
| `pull_request_title` | No | Pull request title | `Update GitHub Action Versions` |
| `pull_request_branch` | No | PR head branch. If set, that branch is force-pushed with lease. Cannot be `main`, `master`, or the repository base branch. | generated (`gh-actions-update-<id>`) |
| `ignore` | No | Comma-separated pins to leave unchanged. Must match the `uses` value **exactly**, including the current version (`actions/checkout@v7`). | empty |
| `skip_pull_request` | No | Write updates and print a diff instead of opening a PR. Fail the step if any file was updated. | `false` |
| `update_version_with` | No | `release-tag`, `release-commit-sha`, or `default-branch-sha` | `release-tag` |
| `release_types` | No | `all`, or a comma-separated combination of `major`, `minor`, `patch` | `all` |
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
- uses: actions/checkout@v7
  with:
    token: ${{ secrets.WORKFLOW_SECRET }}

- name: Run GitHub Actions Version Updater
  id: update
  uses: saadmk11/github-actions-version-updater@v1.0.3
  with:
    token: ${{ secrets.WORKFLOW_SECRET }}

- name: Use the pull request number
  if: steps.update.outputs.GHA_UPDATE_PR_NUMBER
  run: |
    echo "Opened PR #${{ steps.update.outputs.GHA_UPDATE_PR_NUMBER }}"
```

### Access token

GitHub's default `${{ secrets.GITHUB_TOKEN }}` cannot push changes to workflow files. Create a [personal access token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens), store it as a repository [Actions secret](https://docs.github.com/en/actions/security-guides/using-secrets-in-github-actions), and pass it as `token` on both `actions/checkout` and this action. Keep checkout's credential persistence enabled (the default): checkout authenticates Git pushes, and this action's token authenticates GitHub API requests.

The `permissions: contents: read` setting in the examples limits GitHub's automatically generated `GITHUB_TOKEN`. It does not restrict the PAT, whose write access is configured separately. See [workflow permissions](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#permissions).

#### Classic PAT

Create a [classic token](https://github.com/settings/tokens) with both scopes:

| Scope | Access |
| --- | --- |
| `repo` | Push the branch and open the pull request. `public_repo` is enough if the repository is public. |
| `workflow` | Update files under `.github/workflows` |

#### Fine-grained PAT

Create a [fine-grained token](https://github.com/settings/personal-access-tokens/new) for this repository (resource owner is the account or organization that owns it; repository access is **Only select repositories** or **All repositories**):

| Permission | Access |
| --- | --- |
| Contents | Read and write |
| Workflows | Read and write |
| Pull requests | Read and write |
| Metadata | Read-only (granted automatically) |

### Example workflows

#### All inputs

Replace committer details, reviewer names, team slugs, labels, ignored pins, and paths with values for your repository.

```yaml
name: GitHub Actions Version Updater

on:
  workflow_dispatch:
  schedule:
    - cron: "0 0 * * 0"

permissions:
  contents: read

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          token: ${{ secrets.WORKFLOW_SECRET }}

      - name: Run GitHub Actions Version Updater
        uses: saadmk11/github-actions-version-updater@v1.0.3
        with:
          token: ${{ secrets.WORKFLOW_SECRET }}
          committer_username: "actions-bot"
          committer_email: "actions-bot@users.noreply.github.com"
          commit_message: "chore: bump GitHub Actions"
          pull_request_title: "chore: bump GitHub Actions"
          pull_request_branch: "actions-update"
          ignore: "actions/checkout@v7, actions/cache@v4"
          skip_pull_request: "false"
          update_version_with: "release-tag"
          release_types: "minor, patch"
          pull_request_user_reviewers: "octocat, hubot"
          pull_request_team_reviewers: "justice-league"
          pull_request_labels: "dependencies, automated"
          extra_workflow_locations: "deploy/workflows, path/to/workflow.yaml"
```

#### Write updates without a pull request

Writes updated files and prints a diff. The step fails if updates were written and succeeds if nothing changed. It does not commit or push; another step or a person can commit the files.

```yaml
- name: Run GitHub Actions Version Updater
  uses: saadmk11/github-actions-version-updater@v1.0.3
  with:
    token: ${{ secrets.WORKFLOW_SECRET }}
    skip_pull_request: "true"
```

### Git LFS

If the repository uses [Git LFS](https://git-lfs.github.com/), install Git LFS on the runner when its hooks are needed. If Git LFS is unavailable, use `lfs: false` during checkout and remove any remaining LFS hooks before this action runs. Otherwise branch creation or pushing can fail. Remove the files below only if they are LFS hooks.

```yaml
- uses: actions/checkout@v7
  with:
    token: ${{ secrets.WORKFLOW_SECRET }}
    lfs: false

- name: Remove LFS hooks
  shell: bash
  run: |
    rm -f "$(git rev-parse --git-path hooks/post-checkout)" \
          "$(git rev-parse --git-path hooks/pre-push)"

- name: Run GitHub Actions Version Updater
  uses: saadmk11/github-actions-version-updater@v1.0.3
  with:
    token: ${{ secrets.WORKFLOW_SECRET }}
```

### Alternative

[Dependabot](https://docs.github.com/en/code-security/concepts/supply-chain-security/dependabot-version-updates#updates-for-actions) can also update GitHub Actions, including references pinned to commit SHAs.

---

## Python package

**update-gha** is the CLI the Action runs. Use it locally or in another CI system.

[PyPI](https://pypi.org/project/update-gha/) · [Changelog](CHANGELOG.md) · [Issues](https://github.com/saadmk11/github-actions-version-updater/issues)

- Scans `.github/workflows` plus extra files or directories
- Rewrites only the version token (YAML structure, quotes, user comments, and line endings stay)
- SHA pins written with `release-commit-sha` get a `# tag` comment (the matching release tag)
- Three version sources: release tag, release commit SHA, default-branch SHA
- SemVer filters (`major` / `minor` / `patch`)
- `--check`, `--dry-run`, `--diff`, `--fail-on-update`, and JSON output
- Optional `--pull-request` (install `update-gha[action]`)
- Config from CLI flags, `GHA_UPDATE_*` environment variables, or `[tool.update-gha]` in `pyproject.toml`

### Install

Requires **Python 3.12+**.

```bash
# Run once without installing
uvx update-gha --help

# Install with pip
pip install update-gha

# Add to a uv project's development dependencies
uv add --dev update-gha
uv run update-gha --check

# Install as a user-wide tool
uv tool install update-gha
```

Install the `[action]` extra for `--pull-request` support:

```bash
pip install 'update-gha[action]'
uv add --dev 'update-gha[action]'
uv tool install 'update-gha[action]'
```

### How the CLI works

1. Scan `.github/workflows` (and any extra paths) for `uses:` pins.
2. Ask GitHub for a newer release or commit, unless the pin is ignored.
3. Rewrite only the version token.
4. If you passed `--pull-request` and files were written, commit, push, and open a PR.

| Situation | Token needed? |
| --- | --- |
| Public actions, local rewrite / `--check` / `--dry-run` | Optional. A token provides a higher API rate limit. |
| Private action repositories | Yes |
| `--pull-request` | Yes, plus `owner/repo` (`--repository` or `GITHUB_REPOSITORY`) |

### Command examples

```bash
update-gha                          # rewrite workflow files in place
update-gha --check                  # do not write; exit 1 if any pin would change
update-gha --dry-run --diff         # do not write; print the plan and a unified diff
update-gha --fail-on-update         # write, then exit 1 if anything was written
update-gha --format json
update-gha --ignore 'actions/checkout@v7'
update-gha --update-version-with release-tag --release-types 'minor,patch'
update-gha path/to/extra.yaml
```

Open a pull request (needs `update-gha[action]`):

```bash
export GITHUB_TOKEN=...
export GITHUB_REPOSITORY=owner/repo
update-gha --pull-request
```

`--token` and `--repository` work instead of those environment variables. Git push authentication must already be configured; the token option authenticates GitHub API requests. Prefer an environment variable for the token to keep it out of process arguments. Tracked files must be clean so the commit contains only updater changes. Unrelated untracked files are left alone.

### Configuration

Settings are applied in this order, highest priority first:

1. CLI flags
2. Environment variables (`GHA_UPDATE_*`, plus `GITHUB_TOKEN` / `GITHUB_REPOSITORY`)
3. `[tool.update-gha]` in the nearest `pyproject.toml` (walks up from the current directory)
4. Built-in defaults

```bash
export GITHUB_TOKEN=...
export GHA_UPDATE_IGNORE_ACTIONS='actions/checkout@v7'
export GHA_UPDATE_UPDATE_VERSION_WITH=release-tag
export GHA_UPDATE_RELEASE_TYPES='minor,patch'
update-gha
```

```toml
[tool.update-gha]
ignore_actions = ["actions/checkout@v7"]
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
| `--update-version-with` | `release-tag`, `release-commit-sha` (SHA plus a `# tag` comment), or `default-branch-sha`. | `release-tag` |
| `--release-types` | `major`, `minor`, `patch`, or `all`. No effect on `default-branch-sha`. | `all` |
| `--extra-workflow-locations` | Extra files or directories, comma-separated. Directories are recursive. | empty |
| `PATHS` | Extra files or directories as positional arguments. Same role as `--extra-workflow-locations`. | none |
| `--check` | Do not write. Exit 1 if any pin would change. | off |
| `--dry-run` | Do not write. Exit 0 even if updates exist. | off |
| `--diff` | Print a unified diff with text output. Works with writing, `--check`, and `--dry-run`. | off |
| `--fail-on-update` | Write, then exit 1 if any file was written. Incompatible with `--pull-request`, `--check`, and `--dry-run`. | off |
| `--format` | `text` or `json`. JSON sends logs to stderr. | `text` |
| `--verbose` (`-v`) / `--quiet` (`-q`) | Debug logs, or warnings and errors only. Mutually exclusive. | off |
| `--pull-request` / `--no-pull-request` | Enable or disable PR creation. Requires `update-gha[action]`, a token, a repository name, configured Git push authentication, and a clean tracked working tree. | off |
| `--repository` | `owner/repo` that receives the PR. Also `GITHUB_REPOSITORY`. Unused for a local rewrite. | unset |
| `--committer-username` | Git author and committer name for the PR commit. | `github-actions[bot]` |
| `--committer-email` | Git author and committer email for the PR commit. | `github-actions[bot]@users.noreply.github.com` |
| `--commit-message` | Message for the PR commit. | `Update GitHub Action Versions` |
| `--pull-request-title` | Title of the pull request. | `Update GitHub Action Versions` |
| `--pull-request-branch` | Head branch. Omit for a unique name; a given name is force-pushed with lease. Cannot be `main`, `master`, or the repository base branch. | generated (`gh-actions-update-<id>`) |
| `--pull-request-reviewers` | Usernames requested on a **new** PR, comma-separated. | empty |
| `--pull-request-teams` | Team slugs requested on a **new** PR, comma-separated. | empty |
| `--pull-request-labels` | Labels added on a **new** PR, comma-separated. | empty |
| `--version` | Print the package version and exit. | — |
| `--help` | Show available options and exit. | — |

See `update-gha --help` for the full text.

---

## Development

The package lives in `src/update_gha`. Tests are in `tests/`. Tooling is configured in `pyproject.toml` and run with [uv](https://docs.astral.sh/uv/) (0.13.4 or newer).

### Prerequisites

- Python **3.14** for the development environment; the package supports **3.12+**
- [uv](https://docs.astral.sh/uv/) **0.13.4** or newer
- Git for the integration tests

### Setup

```bash
git clone https://github.com/saadmk11/github-actions-version-updater.git
cd github-actions-version-updater
uv sync --locked --all-groups --all-extras
```

This installs the editable package, the `[action]` extra, and the `test`, `lint`, `typing`, and `tox` development groups.

### Layout

| Path | Role |
| --- | --- |
| `src/update_gha/` | Core package: scan, rewrite, GitHub lookup, config, models |
| `src/update_gha/cli/` | `update-gha` console script |
| `src/update_gha/action/` | Git + pull-request helpers (optional extra) |
| `tests/` | Pytest suite; `tests/fixtures/` are YAML rewrite pairs |
| `action.yaml` | Composite GitHub Action with an exact PyPI package pin |
| `tests/packaging/` | Release metadata and fresh wheel/sdist installation checks |
| `.github/workflows/ci.yaml` | Lint and test matrix |

### Tests

```bash
uv run --locked tox run -e py312,py313,py314,py315
uv run --locked tox run -e base,coverage
uv run --locked tox run -e minimum,latest
```

Tox tests the installed wheel. Normal environments use `uv.lock`; `minimum` and `latest` resolve dependencies independently. The `coverage` environment requires **100%** statement and branch coverage. Warnings fail the suite. The `base` environment runs without GitPython.

Install the required interpreters with `uv python install 3.12 3.13 3.14 3.15`. Tests use controlled HTTP responses and temporary Git repositories without contacting GitHub.

```bash
uv run --locked pytest tests/test_rewrite.py          # one file
uv run --locked pytest tests/test_cli.py::test_help   # one test
```

Check the distributions exactly as CI does:

```bash
uv run --locked tox run -e package
```

Checks cover metadata, entry points, and wheel/sdist installations with and without `[action]`. Smoke tests run outside the checkout and exercise JSON output, SHA updates, and pull-request validation.

### Lint and types

```bash
uv run --locked tox run -e lint,type
```

Ruff uses a line length of 88. mypy runs in strict mode on `src` and `tests`.

To apply fixes:

```bash
uv run ruff check --fix .
uv run ruff format .
```

### Pre-commit

[`.pre-commit-config.yaml`](.pre-commit-config.yaml) runs whitespace checks, Ruff, and mypy in isolated hook environments, including on pre-commit.ci. Install [pre-commit](https://pre-commit.com/) separately:

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

### Release

1. Set the version in `pyproject.toml`, the exact `[action]` PyPI pin in `action.yaml`, and the documented action references. Run `uv lock` and commit the lockfile with the release changes.
2. Run `uv run --locked tox` and `uv run --locked python -m tests.packaging.check --release v1.0.3`.
3. Push the matching release tag (`v1.0.3`). The release workflow runs CI, builds with `uv build --no-sources`, validates the distributions, and publishes to PyPI through trusted publishing.
4. Wait for the release workflow to finish before using the new action tag. The action installs the exact matching PyPI version.

### CI

[`.github/workflows/ci.yaml`](.github/workflows/ci.yaml) runs on pushes and pull requests to `main`:

- **test** — the full suite with `[action]` on Python 3.12–3.15 on Linux
- **checks** — Ruff, strict mypy, 100% coverage, base installation, and independent minimum/latest dependency resolutions
- **package** — build and validate wheel and source distributions in fresh base and `[action]` environments on Linux, macOS, and Windows

Release tags run the same CI checks before publishing. The release workflow verifies that the tag, package version, and action's PyPI pin agree, publishes with trusted publishing, and checks the published action entry point.

Python dependencies are updated by Dependabot (`uv`). Action pins in this repository are updated by [`.github/workflows/update-actions.yaml`](.github/workflows/update-actions.yaml).

## License

Released under the [MIT License](LICENSE).
