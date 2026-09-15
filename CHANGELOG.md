# Unreleased

# Version: v1.0.1

* [#74](https://github.com/saadmk11/github-actions-version-updater/issues/74): When `update_version_with` is `release-commit-sha`, write the matching release tag as an inline `# tag` comment (exactly two spaces before `#`) so SHA-to-SHA diffs stay human-readable. Version-like comments are updated; custom comments are left alone.
* [#125](https://github.com/saadmk11/github-actions-version-updater/pull/125): Document classic and fine-grained personal access token permissions.

# Version: v1.0.0

v1 is a rewrite. The GitHub Action is now a composite Action that installs and runs the ``update-gha`` CLI. Action input *names* are the same. How files are found, how pins are rewritten, and what the runner needs are not.

**Breaking**

* **No Docker image.** v0 ran in a container. v1 runs on the job with bash and uv; it installs CPython 3.14 into an isolated venv and does not change the job's ``python`` on ``PATH``. Self-hosted runners need bash and outbound network. They do not need Docker.
* **CLI requires Python 3.12+** if you install ``update-gha`` yourself.
* **Which workflow files are scanned.** v0 asked the GitHub “list workflows” API (usually the workflows registered on the default branch), then opened those paths plus ``extra_workflow_locations``. v1 never calls that API. It reads ``.github/workflows`` and any extra paths from the checkout. After a normal ``actions/checkout`` of the same commit, the set is the same. It can differ if the checkout is sparse, or if the current branch has workflow files that are not on the default branch (v1 will see those; v0 often would not).
* **What gets rewritten in a file.** v0 parsed ``uses:`` to decide *which* pins to bump, then ran a regex over the **whole file**. The same ``owner/repo@v3`` string in a comment, a ``run:`` script, or a URL could change too. v1 only edits the ``uses:`` value. Comments and scripts stay as they are. That is usually what you want; it is a break only if you relied on those extra replacements.
* **What is committed and how named branches are pushed.** v0 ran ``git add .`` and force-pushed named PR branches with ``-f``. v1 stages only the workflow files it changed, and force-pushes named branches with ``--force-with-lease``.

**Added**

* Installable package ``update-gha`` (`pip install update-gha` / `uvx update-gha`).
* Optional ``update-gha --pull-request`` (needs the ``[action]`` extra, or ``GHA_UPDATE_CREATE_PULL_REQUEST``).
* Config from CLI flags, then ``GHA_UPDATE_*`` env vars, then ``[tool.update-gha]`` in ``pyproject.toml``.
* Action output ``GHA_UPDATE_PR_NUMBER`` is unchanged. ``pull-request-number`` is an extra alias.

# Version: v0.9.0

* [#92](https://github.com/saadmk11/github-actions-version-updater/pull/92): [pre-commit.ci] pre-commit autoupdate
* [#100](https://github.com/saadmk11/github-actions-version-updater/pull/100): Update README.md - update checkout versions
* [#106](https://github.com/saadmk11/github-actions-version-updater/pull/106): Fix the actions enclosed in quotes are not updated
* [#115](https://github.com/saadmk11/github-actions-version-updater/pull/115): Base on 3.12-slim-bullseye
* [#116](https://github.com/saadmk11/github-actions-version-updater/pull/116): Update changelog-ci version


# Version: v0.8.1

* [#89](https://github.com/saadmk11/github-actions-version-updater/pull/89): Use `regex.sub` to replace old versions with new ones


# Version: v0.8.0

* [#73](https://github.com/saadmk11/github-actions-version-updater/pull/73): [pre-commit.ci] pre-commit autoupdate
* [#80](https://github.com/saadmk11/github-actions-version-updater/pull/80): [pre-commit.ci] pre-commit autoupdate
* [#82](https://github.com/saadmk11/github-actions-version-updater/pull/82): Update changelog-ci.yaml
* [#83](https://github.com/saadmk11/github-actions-version-updater/pull/83): Set Created Pull Request Number as Action Output
* [#84](https://github.com/saadmk11/github-actions-version-updater/pull/84): Warn users when GitHub Release do not use Semantic Versioning specification
* [#85](https://github.com/saadmk11/github-actions-version-updater/pull/85): Manage Dependencies with pip-tools and Migrate to Pydantic V2


# Version: v0.7.4

* [#60](https://github.com/saadmk11/github-actions-version-updater/pull/60): [pre-commit.ci] pre-commit autoupdate
* [#65](https://github.com/saadmk11/github-actions-version-updater/pull/65): Configuration Management with Pydantic
* [#66](https://github.com/saadmk11/github-actions-version-updater/pull/66): [pre-commit.ci] pre-commit autoupdate
* [#67](https://github.com/saadmk11/github-actions-version-updater/pull/67): use notice, not warning, for unsupported formats
* [#68](https://github.com/saadmk11/github-actions-version-updater/pull/68): Add Fine-grained Personal Access Token Documentation
* [#69](https://github.com/saadmk11/github-actions-version-updater/pull/69): Add Alternatives


# Version: v0.7.3

* [#53](https://github.com/saadmk11/github-actions-version-updater/pull/53): [pre-commit.ci] pre-commit autoupdate
* [#54](https://github.com/saadmk11/github-actions-version-updater/pull/54): Fix badge and update `actions/checkout` in README
* [#55](https://github.com/saadmk11/github-actions-version-updater/pull/55): [Experimental Feature] Pull Request Branch Input Option
* [#56](https://github.com/saadmk11/github-actions-version-updater/pull/56): [Feature] Add Option to Add Labels to Pull Requests
* [#57](https://github.com/saadmk11/github-actions-version-updater/pull/57): [Enhancement] Handle Updates for GitHub Actions that are Located Inside Sub-Directories
* [#58](https://github.com/saadmk11/github-actions-version-updater/pull/58): Update changelog-ci.yaml


# Version: v0.7.2

* [#38](https://github.com/saadmk11/github-actions-version-updater/pull/38): [pre-commit.ci] pre-commit autoupdate
* [#42](https://github.com/saadmk11/github-actions-version-updater/pull/42): [pre-commit.ci] pre-commit autoupdate
* [#44](https://github.com/saadmk11/github-actions-version-updater/pull/44): Document required workaround for LFS-enabled repositories
* [#45](https://github.com/saadmk11/github-actions-version-updater/pull/45): [pre-commit.ci] pre-commit autoupdate
* [#46](https://github.com/saadmk11/github-actions-version-updater/pull/46): [pre-commit.ci] pre-commit autoupdate
* [#50](https://github.com/saadmk11/github-actions-version-updater/pull/50): Try Git Safe Directory to Resolve `fatal: not in a git directory`
* [#51](https://github.com/saadmk11/github-actions-version-updater/pull/51): [pre-commit.ci] pre-commit autoupdate


# Version: v0.7.1

* [#32](https://github.com/saadmk11/github-actions-version-updater/pull/32): ci: update checkout version
* [#33](https://github.com/saadmk11/github-actions-version-updater/pull/33): Handle Workflow File Not Found Error
* [#34](https://github.com/saadmk11/github-actions-version-updater/pull/34): Add Option to Specify Custom Workflow File/Directory Paths
* [#35](https://github.com/saadmk11/github-actions-version-updater/pull/35): Add GitHub Actions Version Updater
* [#36](https://github.com/saadmk11/github-actions-version-updater/pull/36): Update GitHub Action Versions


# Version: v0.7.0

* [#12](https://github.com/saadmk11/github-actions-version-updater/pull/12): Allow custom commit message and pull request title
* [#19](https://github.com/saadmk11/github-actions-version-updater/pull/19): Add Option to Use Commit SHA as a Version and FIx Latest Release Version Resolver
* [#17](https://github.com/saadmk11/github-actions-version-updater/pull/17): Refactor Code and Use `github-action-utils` for logging
* [#24](https://github.com/saadmk11/github-actions-version-updater/pull/24): Add Option to Request Reviews for Generated Pull Request
* [#18](https://github.com/saadmk11/github-actions-version-updater/pull/18): Add Option to Skip Pull Request
* [#26](https://github.com/saadmk11/github-actions-version-updater/pull/26): Add Option to use Release Types (major, minor, patch) for Updates
* [#27](https://github.com/saadmk11/github-actions-version-updater/pull/27): Improve Documentation


# Version: v0.5.6

* [#9](https://github.com/saadmk11/github-actions-version-updater/pull/9): Update marketplace badge URL
* [#10](https://github.com/saadmk11/github-actions-version-updater/pull/10): Remove duplicate changes from pull request body and improve code


# Version: v0.5.5

* [#6](https://github.com/saadmk11/github-actions-version-updater/pull/6): Fix badge URL
* [#7](https://github.com/saadmk11/github-actions-version-updater/pull/7): Fix inconsistent naming


# Version: v0.5.0

* [#1](https://github.com/saadmk11/github-actions-version-updater/pull/1): Create LICENSE
* [#2](https://github.com/saadmk11/github-actions-version-updater/pull/2): Add ignore option to ignore particular action updates
* [#3](https://github.com/saadmk11/github-actions-version-updater/pull/3): Add documentation
* [#4](https://github.com/saadmk11/github-actions-version-updater/pull/4): Add Changelog CI
