## GitHub Actions Version Updater

[![GitHub release (latest by date)](https://img.shields.io/github/v/release/saadmk11/github-actions-version-updater?style=flat-square)](https://github.com/saadmk11/github-actions-version-updater/releases/latest)
[![GitHub](https://img.shields.io/github/license/saadmk11/github-actions-version-updater?style=flat-square)](https://github.com/saadmk11/github-actions-version-updater/blob/main/LICENSE)
[![GitHub Marketplace](https://img.shields.io/badge/Get%20It-on%20Marketplace-orange?style=flat-square)](https://github.com/marketplace/actions/github-actions-version-updater)
[![GitHub stars](https://img.shields.io/github/stars/saadmk11/github-actions-version-updater?color=success&style=flat-square)](https://github.com/saadmk11/github-actions-version-updater/stargazers)
![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/saadmk11/github-actions-version-updater/changelog-ci.yaml?label=Changelog%20CI&style=flat-square)

**GitHub Actions Version Updater** is a GitHub Action that is used to **Update All GitHub Actions** in a Repository
and create a **pull request** with the updates (if enabled).
It is an automated dependency updater similar to GitHub's **Dependabot** but for GitHub Actions.

### How Does It Work?

* GitHub Actions Version Updater first goes through all the **workflows**
  in a repository and **checks for updates** for each of the action used in those workflows.

* If an update is found and if that action is **not ignored** then the workflows are updated
  with the **new version** of the action being used.

* If at least one workflow file is updated then a new branch is created with the changes and pushed to GitHub. (If enabled)

* Finally, a pull request is created with the newly created branch. (If enabled)

### Supported Version Fetch Sources

- **`release-tag` (default):** Uses **specific release tag** from **the latest release** to update a GitHub Action. (e.g. `actions/checkout@v1.2.3`)

- **`release-commit-sha`:** Uses the **latest release tag commit SHA** to update a GitHub Action. (e.g. `actions/checkout@c18e2a1b1a95d0c5c63af210857e8718a479f56f`)

- **`default-branch-sha`:** Uses **default branch** (e.g: `main`, `master`) **latest commit SHA** to update a GitHub Action. (e.g. `actions/checkout@c18e2a1b1a95d0c5c63af210857e8718a479f56f`)

You can use `update_version_with` input option to select one of them. (e.g. `update_version_with: 'default-branch-sha'`)

### Release Types

- **`all` (default):** Actions with **any** new release will be updated.
- **`major`:** Actions with only new **major** release will be updated.
- **`minor`:** Actions with only new **minor** release will be updated.
- **`patch`:** Actions with only new **patch** release will be updated.

You can use `release_types` input option to select one/all of them. (e.g. `"major, minor"`)

### Usage

We recommend running this action on a [`schedule`](https://docs.github.com/en/actions/reference/events-that-trigger-workflows#schedule)
event or a [`workflow_dispatch`](https://docs.github.com/en/actions/reference/events-that-trigger-workflows#workflow_dispatch) event.

To integrate `GitHub Actions Version Updater` on your repository, create a `YAML`  file
inside `.github/workflows/` directory (e.g: `.github/workflows/updater.yaml`) add the following lines into the file:

```yaml
name: GitHub Actions Version Updater

# Controls when the action will run.
on:
  schedule:
    # Automatically run on every Sunday
    - cron:  '0 0 * * 0'

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v3
        with:
          # [Required] Access token with `workflow` scope.
          token: ${{ secrets.WORKFLOW_SECRET }}

      - name: Run GitHub Actions Version Updater
        uses: saadmk11/github-actions-version-updater@v0.8.1
        with:
          # [Required] Access token with `workflow` scope.
          token: ${{ secrets.WORKFLOW_SECRET }}
```

### Workflow input options

These are the inputs that can be provided on the workflow.

| Name                                 | Required | Description                                                                                                                                                                                                                                                                         | Default                                        | Example                                    |
|--------------------------------------|----------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------|--------------------------------------------|
| `token`                              | Yes      | GitHub Access Token with `workflow` scope (The Token needs to be added to the actions secrets)                                                                                                                                                                                      | `null`                                         | `${{ secrets.WORKFLOW_SECRET }}`           |
| `committer_username`                 | No       | Name of the user who will commit the changes to GitHub                                                                                                                                                                                                                              | "github-actions[bot]"                          | "Test User"                                |
| `committer_email`                    | No       | Email Address of the user who will commit the changes to GitHub                                                                                                                                                                                                                     | "github-actions[bot]@users.noreply.github.com" | "test@test.com"                            |
| `commit_message`                     | No       | Commit message for the commits created by the action                                                                                                                                                                                                                                | "Update GitHub Action Versions"                | "Custom Commit Message"                    |
| `pull_request_title`                 | No       | Title of the pull requests generated by the action                                                                                                                                                                                                                                  | "Update GitHub Action Versions"                | "Custom PR Title"                          |
| `pull_request_branch` (Experimental) | No       | The pull request branch name. (If provided, the action will force push to the branch)                                                                                                                                                                                               | "gh-actions-update-<timestamp>"                | "github/actions-update"                    |
| `ignore`                             | No       | A comma separated string of GitHub Actions to ignore updates for                                                                                                                                                                                                                    | `null`                                         | "actions/checkout@v2, actions/cache@v2"    |
| `skip_pull_request`                  | No       | If **"true"**, the action will only check for updates and if any update is found the job will fail and update the build summary with the diff (**Options:** "true", "false")                                                                                                        | "false"                                        | "true"                                     |
| `update_version_with`                | No       | Use The Latest Release Tag/Commit SHA or Default Branch Commit SHA to update the actions (**options:** "release-tag", "release-commit-sha", "default-branch-sha"')                                                                                                                  | "release-tag"                                  | "release-commit-sha"                       |
| `release_types`                      | No       | A comma separated string of release types to use when updating the actions. By default, all release types are used to update the actions. Only Applicable for **"release-tag", "release-commit-sha"** (**Options:** "major", "minor", "patch" **[one or many seperated by comma]**) | "all"                                          | "minor, patch"                             |
| `pull_request_user_reviewers`        | No       | A comma separated string (usernames) which denotes the users that should be added as reviewers to the pull request                                                                                                                                                                  | `null`                                         | "octocat, hubot, other_user"               |
| `pull_request_team_reviewers`        | No       | A comma separated string (team slugs) which denotes the teams that should be added as reviewers to the pull request                                                                                                                                                                 | `null`                                         | "justice-league, other_team"               |
| `pull_request_labels`                | No       | A comma separated string (label names) which denotes the labels which will be added to the pull request                                                                                                                                                                             | `null`                                         | "dependencies, automated"               |
| `extra_workflow_locations`           | No       | A comma separated string of file or directory paths to look for workflows. By default, only the workflow files in the `.github/workflows` directory are checked updates                                                                                                             | `null`                                         | "path/to/directory, path/to/workflow.yaml" |

#### Workflow with all options

```yaml
name: GitHub Actions Version Updater

# Controls when the action will run.
on:
  # can be used to run workflow manually
  workflow_dispatch:
  schedule:
    # Automatically run on every Sunday
    - cron:  '0 0 * * 0'

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v2
        with:
          # [Required] Access token with `workflow` scope.
          token: ${{ secrets.WORKFLOW_SECRET }}

      - name: Run GitHub Actions Version Updater
        uses: saadmk11/github-actions-version-updater@v0.8.1
        with:
          # [Required] Access token with `workflow` scope.
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
          # [Experimental]
          pull_request_branch: "actions-update"
```

### Important Note

GitHub does not allow updating workflow files inside a workflow run.
The token generated by GitHub in every workflow (`${{secrets.GITHUB_TOKEN}}`) does not have
permission to update a workflow. That's why you need to create a [Personal Access Token](https://docs.github.com/en/github/authenticating-to-github/creating-a-personal-access-token)

**For Personal Access Token (Classic):**

You need to create a classic Personal Access Token with these scopes:

- `repo`  (To Push Changes to the Repository and Create Pull Requests)
- `workflow`  (To Update GitHub Action workflow files)

**For Fine-grained Personal Access Token:**

You need to create a Fine-grained Personal Access Token with these Repository permissions:

- `Contents: Read and write`  (To Push Changes to the Repository)
- `Workflows: Read and write`  (To Update GitHub Action workflow files)
- `Pull requests: Read and write`  (To Create Pull Requests)
- `Metadata: Read-only`  (Required by Above Permissions)

After creating the token, you need to add it to your repository actions secrets and use it in the workflow.
To know more about how to pass a secret to GitHub actions you can [Read GitHub Docs](https://docs.github.com/en/actions/reference/encrypted-secrets)

### A note about Git Large File Storage (LFS)

If your repository uses [Git LFS](https://git-lfs.github.com/), you will need to manually remove the LFS-related hook files, otherwise the action
will fail because Git will not be able to create a branch because the lfs executable is not installed inside the
container used by this action.

To work around this, just remove the hook files manually as an extra step **before** this action executes:

```yaml
# ...
jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v3
        with:
          token: ${{ secrets.WORKFLOW_SECRET }}
          lfs: false

      - name: Remove LFS hooks
        # This repository uses Git LFS, but it not being
        # in the container causes the action to fail to create a new branch.
        # Removing the hooks manually is harmless and works around this issue.
        run: |
          rm .git/hooks/post-checkout
          rm .git/hooks/pre-push

      - name: Run GitHub Actions Version Updater
        uses: saadmk11/github-actions-version-updater@v0.8.1
        with:
          # ...
```

### Outputs

| Output Name | Description                             |
| ----------- |-----------------------------------------|
| `GHA_UPDATE_PR_NUMBER` | The number of the created pull request. |

#### Example Workflow

```yaml
name: GitHub Actions Version Updater

# Controls when the action will run.
on:
  # can be used to run workflow manually
  workflow_dispatch:
  schedule:
    # Automatically run on every Sunday
    - cron:  '0 0 * * 0'

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v2
        with:
          # [Required] Access token with `workflow` scope.
          token: ${{ secrets.WORKFLOW_SECRET }}

      - name: Run GitHub Actions Version Updater
        uses: saadmk11/github-actions-version-updater@v0.8.1
        # Required to get the PR number
        id: gha-update
        with:
          # [Required] Access token with `workflow` scope.
          token: ${{ secrets.WORKFLOW_SECRET }}
          skip_pull_request: 'false'
      - name: Get PR Number
        run: echo "The PR Number is ${{ steps.gha-update.outputs.GHA_UPDATE_PR_NUMBER }}"
```

### Alternative

You can also use [Dependabot](https://docs.github.com/en/github/administering-a-repository/keeping-your-actions-up-to-date-with-dependabot) to update your GitHub Actions.


### GitHub Actions Version Updater in Action

![GitHub Actions Version Updater Demo](https://user-images.githubusercontent.com/24854406/113888349-15dbdc00-97e4-11eb-91a6-622828455d1f.gif)


### License

The code in this project is released under the [MIT License](LICENSE).
