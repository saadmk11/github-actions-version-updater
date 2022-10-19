## GitHub Actions Version Updater

[![GitHub release (latest by date)](https://img.shields.io/github/v/release/saadmk11/github-actions-version-updater?style=flat-square)](https://github.com/saadmk11/github-actions-version-updater/releases/latest)
[![GitHub](https://img.shields.io/github/license/saadmk11/github-actions-version-updater?style=flat-square)](https://github.com/saadmk11/github-actions-version-updater/blob/main/LICENSE)
[![GitHub Marketplace](https://img.shields.io/badge/Get%20It-on%20Marketplace-orange?style=flat-square)](https://github.com/marketplace/actions/github-actions-version-updater)
[![GitHub stars](https://img.shields.io/github/stars/saadmk11/github-actions-version-updater?color=success&style=flat-square)](https://github.com/saadmk11/github-actions-version-updater/stargazers)
![GitHub Workflow Status](https://img.shields.io/github/workflow/status/saadmk11/github-actions-version-updater/Changelog%20CI?label=Changelog%20CI&style=flat-square)

**GitHub Actions Version Updater** is a GitHub Action that is used to **Update All GitHub Actions** in a Repository
and create a **pull request** with the updates (if enabled).
It is an automated dependency updater similar to GitHub's **Dependabot** but for GitHub Actions.

### How Does It Work:

* GitHub Actions Version Updater first goes through all the **workflows**
  in a repository and **checks for updates** for each of the action used in those workflows.

* If an update is found and if that action is **not ignored** then the workflows are updated
  with the **new version** of the action being used.

* If at least one workflow file is updated then a new branch is created with the changes and pushed to GitHub. (If enabled)

* Finally, a pull request is created with the newly created branch. (If enabled)

### Supported Version Fetch Sources:

- **`release-tag`** (default): Uses **specific version tag** from **the latest release** to update a GitHub Action. (e.g. `actions/checkout@v1.2.3`)
- **`release-commit-sha`**: Uses **the latest release** tag **commit SHA** to update a GitHub Action. (e.g. `actions/checkout@c18e2a1b1a95d0c5c63af210857e8718a479f56f`)
- **`default-branch-sha`**: Uses **default branch** (e.g: `main`, `master`) **latest commit SHA** to update a GitHub Action. (e.g. `actions/checkout@c18e2a1b1a95d0c5c63af210857e8718a479f56f`)

You can use `update_version_with` input option to select one of them. (e.g. `update_version_with: 'default-branch-sha'`)

### Usage:

We recommend running this action on a [`schedule`](https://docs.github.com/en/actions/reference/events-that-trigger-workflows#schedule)
event or a [`workflow_dispatch`](https://docs.github.com/en/actions/reference/events-that-trigger-workflows#workflow_dispatch) event.

To integrate `GitHub Actions Version Updater` on your repository, create a `YAML`  file
inside `.github/workflows/` directory (`.github/workflows/updater.yaml`) add the following into the file:

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
          # Access token with `workflow` scope is required
          token: ${{ secrets.WORKFLOW_SECRET }}

      - name: Run GitHub Actions Version Updater
        uses: saadmk11/github-actions-version-updater@v0.5.6
        with:
          # [Required] Access token with `workflow` scope.
          token: ${{ secrets.WORKFLOW_SECRET }}
          # [Optional] This will be used to configure git
          # defaults to `github-actions[bot]` if not provided
          committer_username: 'test'
          committer_email: 'test@test.com'
          # [Optional] Allows customizing the commit message
          # defaults to 'Update GitHub Action Versions'
          commit_message: 'Commit Message'
          # [Optional] Allows customizing the pull request title
          # defaults to 'Update GitHub Action Versions'
          pull_request_title: 'Pull Request Title'
          # [Optional] A comma separated string of GitHub Actions to ignore updates for.
          # e.g: 'actions/checkout@v2, actions/cache@v2'
          ignore: 'actions/checkout@v2, actions/cache@v2'
          # [Optional] If set to 'true', the action will only check for updates and
          # exit with a non-zero exit code if an update is found and update the build summary with the diff
          # otherwise it will create a pull request with the changes
          # options: 'false' (default), 'true'
          skip_pull_request: 'false'
          # [Optional] Use The Latest Release Tag/Commit SHA or Default Branch Commit SHA to update the actions
          # options: "release-tag" (default), "release-commit-sha", "default-branch-sha"'
          update_version_with: 'release-tag'
          # [Optional] A comma separated string which denotes the users (usernames)
          # that should be added as reviewers to the pull request
          pull_request_user_reviewers: "octocat, hubot, other_user"
          # [Optional] A comma separated string which denotes the teams (team slugs)
          # that should be added as reviewers to the pull request
          pull_request_team_reviewers: "justice-league, other_team"
```

### Important Note:

GitHub does not allow updating workflow files inside a workflow run.
The token generated by GitHub in every workflow (`${{secrets.GITHUB_TOKEN}}`) does not have
permission to update a workflow. That's why you need to create a [Personal Access Token](https://docs.github.com/en/github/authenticating-to-github/creating-a-personal-access-token)
with **repo** and **workflow** scope and pass it to the action.

To know more about how to pass a secret to GitHub actions you can [Read GitHub Docs](https://docs.github.com/en/actions/reference/encrypted-secrets)

### GitHub Actions Version Updater in Action:

![GitHub Actions Version Updater Demo](https://user-images.githubusercontent.com/24854406/113888349-15dbdc00-97e4-11eb-91a6-622828455d1f.gif)


### License

The code in this project is released under the [MIT License](LICENSE).
