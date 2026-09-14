## GitHub Actions Version Updater

[![GitHub release (latest by date)](https://img.shields.io/github/v/release/saadmk11/github-actions-version-updater?style=flat-square)](https://github.com/saadmk11/github-actions-version-updater/releases/latest)
[![GitHub](https://img.shields.io/github/license/saadmk11/github-actions-version-updater?style=flat-square)](https://github.com/saadmk11/github-actions-version-updater/blob/main/LICENSE)
[![GitHub Marketplace](https://img.shields.io/badge/Get%20It-on%20Marketplace-orange?style=flat-square)](https://github.com/marketplace/actions/github-actions-version-updater)
[![GitHub stars](https://img.shields.io/github/stars/saadmk11/github-actions-version-updater?color=success&style=flat-square)](https://github.com/saadmk11/github-actions-version-updater/stargazers)
![GitHub Workflow Status](https://img.shields.io/github/actions/workflow-status/saadmk11/github-actions-version-updater/ci.yaml?label=CI&style=flat-square)

**GitHub Actions Version Updater** finds outdated `uses:` pins in workflow YAML
and rewrites only the version token. The composite action can then open a
**pull request** with the changes. It is an automated dependency updater
similar to GitHub's **Dependabot**, but focused on GitHub Actions.

It ships as two pieces in this repository:

1. **`gha-update`** — an installable Python CLI (`import gha_update`).
2. **A composite GitHub Action** — installs the CLI plus the ``action`` extra
   from the action checkout with a locked `uv sync --frozen --extra action`
   and then commits / opens a pull request.

Tags `v0.9.0` and earlier run as a Docker action. Newer tags run as a composite
action on the job runner. **Inputs, defaults, and the `GHA_UPDATE_PR_NUMBER`
output are unchanged.**

### How Does It Work?

* The updater walks workflow files (`.github/workflows` plus any extra paths)
  and checks GitHub for a newer version of each `uses:` action.
* If an update is found and that action is not ignored, only the version token
  is rewritten. Comments, quotes, indentation, and line endings stay as they
  were.
* The composite action then creates a branch, commits, and opens a pull request
  (unless `skip_pull_request` is set).

### Supported Version Fetch Sources

- **`release-tag` (default):** Latest release tag (e.g. `actions/checkout@v1.2.3`)
- **`release-commit-sha`:** Commit SHA of the latest release tag
- **`default-branch-sha`:** Latest commit SHA of the action's default branch

Set `update_version_with` to choose one.

### Release Types

- **`all` (default):** Any new release
- **`major` / `minor` / `patch`:** Only that kind of bump

Use `release_types` (e.g. `"major, minor"`). Applies to `release-tag` and
`release-commit-sha`.

### GitHub Action usage

Run this action on a [`schedule`](https://docs.github.com/en/actions/reference/events-that-trigger-workflows#schedule)
or [`workflow_dispatch`](https://docs.github.com/en/actions/reference/events-that-trigger-workflows#workflow_dispatch)
event.

```yaml
name: GitHub Actions Version Updater

on:
  schedule:
    - cron:  '0 0 * * 0'

jobs:
  build:
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

The action is composite. It installs [uv](https://docs.astral.sh/uv/), runs
`uv sync --frozen` against the action checkout's `uv.lock`, updates workflow
files, then commits and opens a pull request. Existing `with:` blocks from
older versions keep working.

### Workflow input options

| Name | Required | Description | Default | Example |
|---|---|---|---|---|
| `token` | Yes | GitHub Access Token with `workflow` scope | `null` | `${{ secrets.WORKFLOW_SECRET }}` |
| `committer_username` | No | Name of the user who will commit the changes | `github-actions[bot]` | `Test User` |
| `committer_email` | No | Email of the user who will commit the changes | `github-actions[bot]@users.noreply.github.com` | `test@test.com` |
| `commit_message` | No | Commit message | `Update GitHub Action Versions` | `Custom Commit Message` |
| `pull_request_title` | No | Pull request title | `Update GitHub Action Versions` | `Custom PR Title` |
| `pull_request_branch` (Experimental) | No | PR branch name. If set, the action force-pushes that branch | `gh-actions-update-<timestamp>` | `github/actions-update` |
| `ignore` | No | Comma-separated actions to skip | `null` | `actions/checkout@v2, actions/cache@v2` |
| `skip_pull_request` | No | If `"true"`, update files, fail the job, and write the diff to the job summary | `"false"` | `"true"` |
| `update_version_with` | No | `release-tag`, `release-commit-sha`, or `default-branch-sha` | `release-tag` | `release-commit-sha` |
| `release_types` | No | `all`, or any of `major`, `minor`, `patch` | `all` | `minor, patch` |
| `pull_request_user_reviewers` | No | Comma-separated usernames | `null` | `octocat, hubot, other_user` |
| `pull_request_team_reviewers` | No | Comma-separated team slugs | `null` | `justice-league, other_team` |
| `pull_request_labels` | No | Comma-separated label names | `null` | `dependencies, automated` |
| `extra_workflow_locations` | No | Extra files or directories to scan | `null` | `path/to/directory, path/to/workflow.yaml` |

#### Workflow with all options

```yaml
name: GitHub Actions Version Updater

on:
  workflow_dispatch:
  schedule:
    - cron:  '0 0 * * 0'

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.WORKFLOW_SECRET }}

      - name: Run GitHub Actions Version Updater
        uses: saadmk11/github-actions-version-updater@v1.0.0
        with:
          token: ${{ secrets.WORKFLOW_SECRET }}
          committer_username: 'Test'
          committer_email: 'test@test.com'
          commit_message: 'Commit Message'
          pull_request_title: 'Pull Request Title'
          ignore: 'actions/checkout@v2, actions/cache@v2'
          skip_pull_request: 'false'
          update_version_with: 'release-tag'
          release_types: "minor, patch"
          pull_request_user_reviewers: "octocat, hubot, other_user"
          pull_request_team_reviewers: "justice-league, other_team"
          pull_request_labels: "dependencies, automated"
          extra_workflow_locations: "path/to/directory, path/to/workflow.yaml"
          pull_request_branch: "actions-update"
```

### Important Note

GitHub does not allow updating workflow files with `${{ secrets.GITHUB_TOKEN }}`.
Create a [Personal Access Token](https://docs.github.com/en/github/authenticating-to-github/creating-a-personal-access-token)
and store it as a repository secret.

**Classic PAT scopes:** `repo`, `workflow`

**Fine-grained PAT repository permissions:**

- `Contents: Read and write`
- `Workflows: Read and write`
- `Pull requests: Read and write`
- `Metadata: Read-only`

See [GitHub Docs](https://docs.github.com/en/actions/reference/encrypted-secrets)
for passing secrets to actions.

### A note about Git Large File Storage (LFS)

The composite action uses the job runner's `git`, so GitHub-hosted runners
already have `git-lfs` and the old Docker-era hook workaround is usually
unnecessary. If a self-hosted runner is missing `git-lfs` and checkout installed
LFS hooks, remove those hooks before this action runs:

```yaml
      - name: Remove LFS hooks
        run: |
          rm -f .git/hooks/post-checkout
          rm -f .git/hooks/pre-push
```

### Outputs

| Output Name | Description |
| --- | --- |
| `GHA_UPDATE_PR_NUMBER` | The number of the created pull request. |
| `pull-request-number` | Same value, composite-style name. |

```yaml
      - name: Run GitHub Actions Version Updater
        uses: saadmk11/github-actions-version-updater@v1.0.0
        id: gha-update
        with:
          token: ${{ secrets.WORKFLOW_SECRET }}
      - name: Get PR Number
        run: echo "The PR Number is ${{ steps.gha-update.outputs.GHA_UPDATE_PR_NUMBER }}"
```

### Standalone CLI

Requires Python 3.12 or newer.

```bash
uvx gha-update --help
# or
pip install gha-update
gha-update
```

```bash
gha-update                          # rewrite workflow files in place
gha-update --check                  # exit 1 if updates would be applied
gha-update --dry-run --diff         # show the plan and a unified diff
gha-update --format json
gha-update --ignore 'actions/checkout@v4'
gha-update --update-version-with release-tag --release-types 'minor,patch'
gha-update path/to/extra.yaml
```

A GitHub token is optional for public actions (`GITHUB_TOKEN` or `--token`).
It is recommended so you stay under the authenticated API rate limit.

Project defaults can live in `pyproject.toml`:

```toml
[tool.gha-update]
ignore_actions = ["actions/checkout@v4"]
update_version_with = "release-tag"
release_types = ["minor", "patch"]
extra_workflow_locations = ["deploy/workflows"]
```

Precedence: CLI flags, then `GHA_UPDATE_*` / `GITHUB_TOKEN` / `GITHUB_REPOSITORY`,
then this table, then built-in defaults.

The default install is the scanner only. Git commit / pull-request support is
an optional extra (GitPython):

```bash
pip install 'gha-update[action]'
gha-update-pr
```

`gha-update` never commits. The composite action installs the extra and runs
`gha-update-pr` after files are rewritten.

### Alternative

You can also use [Dependabot](https://docs.github.com/en/github/administering-a-repository/keeping-your-actions-up-to-date-with-dependabot)
to update GitHub Actions.

### Development

This project is managed with [uv](https://docs.astral.sh/uv/). Local development
uses Python 3.14 (see `.python-version`). The package supports 3.12–3.14.

```bash
uv sync --all-extras
uv run pytest
uv run ruff check .
uv run ruff format .
uv run mypy
uv run gha-update --help
```

Python dependencies are updated by Dependabot (`uv`). GitHub Action pins in
this repository are updated by `.github/workflows/update-actions.yaml` so the
two bots do not open conflicting PRs.

### Publishing

Releases are tagged `vX.Y.Z`. `.github/workflows/release.yaml` builds the
package, smoke-tests the wheel and sdist, then publishes to PyPI with
[Trusted Publishing](https://docs.pypi.org/trusted-publishers/). No PyPI token
is stored in GitHub.

Configure a **pending trusted publisher** on PyPI once:

| Field | Value |
| --- | --- |
| PyPI project | `gha-update` |
| Owner | `saadmk11` |
| Repository | `github-actions-version-updater` |
| Workflow | `release.yaml` |
| Environment | `pypi` |

Create a GitHub Environment named `pypi`. Then:

```bash
uv version --bump minor   # or set the version explicitly
git commit -am "Release v1.0.0"
git tag v1.0.0
git push origin main --tags
```

The composite action does not install from PyPI. It always installs the package
from `${{ github.action_path }}`, so a missing first PyPI upload cannot break
Marketplace users.

### License

The code in this project is released under the [MIT License](LICENSE).
