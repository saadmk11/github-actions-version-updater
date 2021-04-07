import os
import subprocess
import time

import requests
import yaml


class GitHubActionUpgrade:

    github_api_url = 'https://api.github.com'
    action_label = 'uses'

    def __init__(self, repository, base_branch, token):
        self.repository = repository
        self.base_branch = base_branch
        self.token = token
        self.workflow_updated = False

    def run(self):
        workflows = self.get_workflows()
        comment = '#### GitHub Actions Version Upgrades\n'

        if not workflows:
            _print_message(
                'warning', f'No Work flow found in {self.repository}.'
            )
            return

        for workflow_path in workflows:
            _print_message(
                'debug', f'Checking "{workflow_path}" for updates....'
            )
            with open(workflow_path, 'r+') as file:
                file_data = file.read()
                data = yaml.load(file_data, Loader=yaml.FullLoader)
                old_action_set = set(self.get_all_actions(data))
                updated_config = file_data

                for action in old_action_set:
                    action_repository, version = action.split('@')
                    latest_release = self.get_latest_release(action_repository)

                    if not latest_release:
                        continue

                    updated_action = f'{action_repository}@{latest_release["tag_name"]}'

                    if action != updated_action:
                        _print_message(
                            'debug',
                            f'Found new version for "{action_repository}" on "{workflow_path}".'
                        )
                        comment += self.generate_comment_line(
                            action_repository, latest_release
                        )
                        updated_config = updated_config.replace(
                            action, updated_action
                        )
                        file.seek(0)
                        file.write(updated_config)
                        file.truncate()
                        self.workflow_updated = True

        if self.workflow_updated:
            new_branch = f'gh-action-upgrade-{int(time.time())}'

            subprocess.run(['echo', '::group::Create New Branch'])

            subprocess.run(
                ['git', 'checkout', self.base_branch]
            )
            subprocess.run(
                ['git', 'checkout', '-b', new_branch]
            )
            subprocess.run(['git', 'add', '.'])
            subprocess.run(['git', 'commit', '-m', 'Upgrade GitHub Action Workflow Versions'])

            subprocess.run(['git', 'push', '-u', 'origin', new_branch])

            subprocess.run(['echo', '::endgroup::'])

            current_branch = subprocess.check_output(['git', 'branch'])

            if new_branch in str(current_branch):
                self.create_pull_request(new_branch, comment)


    def create_pull_request(self, branch_name, body):
        """Create pull request on GitHub"""
        url = f'{self.github_api_url}/repos/{self.repository}/pulls'
        payload = {
            'title': 'Upgrade GitHub Action Workflow Versions',
            'head': branch_name,
            'base': self.base_branch,
            'body': body,
        }

        response = requests.post(
            url, json=payload, headers=self.get_request_headers()
        )

        if response.status_code != 201:
            msg = (
                f'Could not create a pull request on '
                f'{self.repository}, status code: {response.status_code}'
            )
            _print_message('error', msg)
        else:
            _print_message(
                'debug',
                f'Creating pull request on {self.repository}.'
            )

    def generate_comment_line(selfself, action_repository, latest_release):
        """Generate Comment line for pull request body"""
        return (
            f"* **{action_repository}** published a new release "
            f"[{latest_release['tag_name']}]({latest_release['html_url']}) "
            f"on {latest_release['published_at']}\n"
        )

    def get_request_headers(self):
        """Get headers for GitHub API request"""
        headers = {
            'Accept': 'application/vnd.github.v3+json'
        }
        # if the user adds `GITHUB_TOKEN` add it to API Request
        # required for `private` repositories
        if self.token:
            headers.update({
                'authorization': 'Bearer {token}'.format(token=self.token)
            })

        return headers

    def get_latest_release(self, action_repository):
        """Get latest release using GitHub API """
        url = f'{self.github_api_url}/repos/{action_repository}/releases/latest'

        response = requests.get(url, headers=self.get_request_headers())
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
                f'{action_repository}, status code: {response.status_code}'
            )
            _print_message('error', msg)

        return data

    def get_workflows(self):
        """Get all workflows of the repository using GitHub API """
        url = f'{self.github_api_url}/repos/{self.repository}/actions/workflows'

        response = requests.get(url, headers=self.get_request_headers())
        data = []

        if response.status_code == 200:
            response_data = response.json()

            for workflow in response_data['workflows']:
                data.append(workflow['path'])
        else:
            msg = (
                f'An error occurred while getting workflows for'
                f'{self.repository}, status code: {response.status_code}'
            )
            _print_message('error', msg)

        return data

    def get_all_actions(self, config):
        """Get all action names from config recursively"""
        if isinstance(config, dict):
            for key, value in config.items():
                if key == self.action_label:
                    yield value
                elif (isinstance(value, dict) or isinstance(value, list)):
                    for item in self.get_all_actions(value):
                        yield item

        elif isinstance(config, list):
            for element in config:
                for item in self.get_all_actions(element):
                    yield item


def _print_message(type, message):
    """Helper function to print colorful outputs in GitHub Actions shell"""
    return subprocess.run(['echo', f'::{type}::{message}'])


if __name__ == '__main__':
    # Default environment variable from GitHub
    # https://docs.github.com/en/actions/configuring-and-managing-workflows/using-environment-variables
    repository = os.environ['GITHUB_REPOSITORY']
    base_branch = os.environ['GITHUB_REF']
    # Token provided from the workflow
    token = os.environ.get('INPUT_TOKEN')
    # Committer username and email address
    username = os.environ['INPUT_COMMITTER_USERNAME']
    email = os.environ['INPUT_COMMITTER_EMAIL']

    # Group: Configure Git
    subprocess.run(['echo', '::group::Configure Git'])

    subprocess.run(['git', 'config', 'user.name', username])
    subprocess.run(['git', 'config', 'user.email', email])

    subprocess.run(['echo', '::endgroup::'])

    # Group: Generate Changelog
    subprocess.run(['echo', '::group::Upgrade GitHub Actions'])

    # Initialize the Changelog CI
    action_upgrade = GitHubActionUpgrade(
        repository, base_branch, token
    )
    action_upgrade.run()

    subprocess.run(['echo', '::endgroup::'])
