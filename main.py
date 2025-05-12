import glob
import json
import os
import subprocess
import time
from functools import cached_property

import requests
import yaml


class GitHubActionsVersionUpdater:
    """Main class that checks for updates and creates pull request"""

    github_api_url = 'https://api.github.com'
    github_url = 'https://github.com/'
    action_label = ['uses', 'action']

    def __init__(self, repository, base_branch, token, paths, workspace, commit_message=None, pr_title=None, ignore_actions=None):
        self.repository = repository
        self.base_branch = base_branch
        self.token = token
        self.commit_message = commit_message or 'Update GitHub Action Versions'
        self.pr_title = pr_title or 'Update GitHub Action Versions'
        self.ignore_actions = self.get_ignored_actions(ignore_actions)
        self.workflow_updated = False
        self.paths = paths.split(';')
        self.workspace = workspace

    @staticmethod
    def get_ignored_actions(json_string):
        """Validate json string and return a set of actions"""
        try:
            ignore = json.loads(json_string)

            if (
                isinstance(ignore, list) and
                all(isinstance(item, str) for item in ignore)
            ):
                return set(ignore)
            else:
                print_message(
                    'Input "ignore" must be a JSON array of strings',
                    message_type='error'
                )
        except Exception:
            print_message(
                (
                    'Invalid input format for "ignore", '
                    'expected JSON array of strings'
                ),
                message_type='error'
            )
        return set()

    @cached_property
    def get_request_headers(self):
        """Get headers for GitHub API request"""
        headers = {
            'Accept': 'application/vnd.github.v3+json'
        }
        # if the user adds `token` add it to API Request
        # required for `private` repositories and creating pull requests
        if self.token:
            headers.update({
                'authorization': 'Bearer {token}'.format(token=self.token)
            })

        return headers

    def versionify(self, v):
        try:
            return tuple(map(int, (v.lstrip("v").split("."))))
        except Exception:
            return (0, 0)

    def run(self):
        """Entrypoint to the GitHub Action"""
        workflow_paths = self.get_workflow_paths()
        pull_request_body = set()

        if not workflow_paths:
            print_message(
                (
                    f'No Workflow found in "{self.repository}". '
                    f'Skipping GitHub Actions Version Update'
                ),
                message_type='warning'
            )
            return

        if self.ignore_actions:
            print_message(f'Actions "{self.ignore_actions}" will be skipped')

        for workflow_path in workflow_paths:
            try:
                with open(workflow_path, 'r+') as file:
                    print_message(
                        f'Checking "{workflow_path}" for updates',
                        message_type='group'
                    )

                    file_data = file.read()
                    updated_config = file_data

                    data = yaml.load(file_data, Loader=yaml.FullLoader)
                    old_action_set = set(self.get_all_actions(data))
                    # Remove ignored actions
                    old_action_set.difference_update(self.ignore_actions)

                    for action in old_action_set:
                        try:
                            action_repository, version = action.split('@')
                        except Exception:
                            print_message(
                                (
                                    f'Action "{action}" seems to be in a wrong format, '
                                    'We currently support only community actions'
                                ),
                                message_type='warning'
                            )
                            continue

                        latest_release = self.get_latest_release(action_repository)

                        if not latest_release:
                            continue

                        if self.versionify(latest_release["tag_name"]) < self.versionify(version):
                            print_message(
                                (
                                    f'Action "{action}" latest release {latest_release["tag_name"]} is '
                                    'lower than current version - skipping'
                                ),
                                message_type='warning'
                            )
                            continue

                        updated_action = (
                            f'{action_repository}@{latest_release["tag_name"]}'
                        )

                        if updated_action in self.ignore_actions:
                            print_message((f'Action "{updated_action}" in ignore list. Skipping'))
                            continue

                        if action != updated_action:
                            print_message(
                                f'Found new version for "{action_repository}"'
                            )
                            pull_request_body.add(
                                self.generate_pull_request_body_line(
                                    action_repository, latest_release
                                )
                            )
                            print_message(
                                f'Updating "{action}" with "{updated_action}"'
                            )
                            updated_config = updated_config.replace(
                                action, updated_action
                            )
                            file.seek(0)
                            file.write(updated_config)
                            file.truncate()
                            self.workflow_updated = True
                        else:
                            print_message(
                                f'No updates found for "{action_repository}"'
                            )

                    print_message('', message_type='endgroup')

            except Exception:
                print_message(f'Skipping "{workflow_path}"')

        if self.workflow_updated:
            new_branch = self.create_new_branch()

            current_branch = subprocess.check_output(
                ['git', 'rev-parse', '--abbrev-ref', 'HEAD']
            )

            if new_branch in str(current_branch):
                print_message('Create Pull Request', message_type='group')

                pull_request_body_str = (
                    '### GitHub Actions Version Updates\n' +
                    ''.join(pull_request_body)
                )
                self.create_pull_request(new_branch, pull_request_body_str)

                print_message('', message_type='endgroup')
        else:
            print_message('Everything is up-to-date! \U0001F389 \U0001F389')

    def create_new_branch(self):
        """Create and push a new branch with the changes"""
        print_message('Create New Branch', message_type='group')

        # Use timestamp to ensure uniqueness of the new branch
        new_branch = f'gh-actions-update-{int(time.time())}'

        subprocess.run(
            ['git', 'checkout', self.base_branch]
        )
        subprocess.run(
            ['git', 'checkout', '-b', new_branch]
        )
        subprocess.run(['git', 'add', '.'])
        subprocess.run(
            ['git', 'commit', '-m', self.commit_message]
        )

        subprocess.run(['git', 'push', '-u', 'origin', new_branch])

        print_message('', message_type='endgroup')

        return new_branch

    def create_pull_request(self, branch_name, body):
        """Create pull request on GitHub"""
        url = f'{self.github_api_url}/repos/{self.repository}/pulls'
        payload = {
            'title': self.pr_title,
            'head': branch_name,
            'base': self.base_branch,
            'body': body,
        }

        response = requests.post(
            url, json=payload, headers=self.get_request_headers
        )

        if response.status_code == 201:
            html_url = response.json()['html_url']
            print_message(f'Pull request opened at {html_url} \U0001F389')
        else:
            msg = (
                f'Could not create a pull request on '
                f'{self.repository}, status code: {response.status_code}'
            )
            print_message(msg, message_type='warning')

    def generate_pull_request_body_line(self, action_repository, latest_release):
        """Generate pull request body line for pull request body"""
        return (
            f"* **[{action_repository}]({self.github_url + action_repository})** "
            "published a new release "
            f"[{latest_release['tag_name']}]({latest_release['html_url']}) "
            f"on {latest_release['published_at']}\n"
        )

    def get_latest_release(self, action_repository):
        """Get latest release using GitHub API """
        url = f'{self.github_api_url}/repos/{action_repository}/releases/latest'

        response = requests.get(url, headers=self.get_request_headers)
        data = {}

        if response.status_code == 200:
            response_data = response.json()

            data = {
                'published_at': response_data['published_at'],
                'html_url': response_data['html_url'],
                'tag_name': response_data['tag_name'],
                'body': response_data['body']
            }
        else:
            # if there is no previous release API will return 404 Not Found
            msg = (
                f'Could not find any release for '
                f'"{action_repository}", status code: {response.status_code}'
            )
            print_message(msg, message_type='warning')

        return data

    def get_workflow_paths(self):
        """Get all workflows of the repository using paths info """
        data = set()
        for path in self.paths:
            data.update(glob.glob(os.path.join(self.workspace, path)))
        return sorted(data)

    def get_all_actions(self, config):
        """Recursively get all action names from config"""
        if isinstance(config, dict):
            for key, value in config.items():
                if key in self.action_label:
                    yield value
                elif isinstance(value, dict) or isinstance(value, list):
                    for item in self.get_all_actions(value):
                        yield item

        elif isinstance(config, list):
            for element in config:
                for item in self.get_all_actions(element):
                    yield item


def print_message(message, message_type=None):
    """Helper function to print colorful outputs in GitHub Actions shell"""
    # docs: https://docs.github.com/en/actions/reference/workflow-commands-for-github-actions
    if not message_type:
        return subprocess.run(['echo', f'{message}'])

    if message_type == 'endgroup':
        return subprocess.run(['echo', '::endgroup::'])

    return subprocess.run(['echo', f'::{message_type}::{message}'])


if __name__ == '__main__':
    # Default environment variable from GitHub
    # https://docs.github.com/en/actions/configuring-and-managing-workflows/using-environment-variables
    repository = os.environ['GITHUB_REPOSITORY']
    workspace = os.environ['GITHUB_WORKSPACE']
    base_branch = os.environ['GITHUB_REF']
    # Token provided from the workflow
    token = os.environ.get('INPUT_TOKEN')
    # Committer username and email address
    username = os.environ['INPUT_COMMITTER_USERNAME']
    email = os.environ['INPUT_COMMITTER_EMAIL']
    # Actions that should not be updated
    ignore = os.environ['INPUT_IGNORE']
    # Commit message
    commit_message = os.environ['INPUT_COMMIT_MESSAGE']
    # Pull Request Title
    pr_title = os.environ['INPUT_PULL_REQUEST_TITLE']
    # paths
    paths = os.environ['INPUT_PATHS']

    # Change to workdir
    os.chdir(workspace)
    subprocess.run(['git', 'config', '--global', '--add', 'safe.directory', workspace])

    # Group: Configure Git
    print_message('Configure Git', message_type='group')

    subprocess.run(['git', 'config', 'user.name', username])
    subprocess.run(['git', 'config', 'user.email', email])

    print_message('', message_type='endgroup')

    # Group: Run Update GitHub Actions
    print_message('Update GitHub Actions', message_type='group')

    # Initialize GitHubActionsVersionUpdater
    actions_version_updater = GitHubActionsVersionUpdater(
        repository, base_branch, token, paths, workspace, commit_message=commit_message, pr_title=pr_title, ignore_actions=ignore
    )
    actions_version_updater.run()

    print_message('', message_type='endgroup')
