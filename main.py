import os
import subprocess
import time

import requests
import yaml


class GitHubActionUpgrade:

    github_api_url = 'https://api.github.com'
    github_url = 'https://github.com/'
    action_label = 'uses'

    def __init__(self, repository, base_branch, token):
        self.repository = repository
        self.base_branch = base_branch
        self.token = token
        self.workflow_updated = False

    def run(self):
        """Entrypoint to the GitHub Action"""
        workflow_paths = self.get_workflow_paths()
        comment = ''

        if not workflow_paths:
            print_message(
                f'No Work flow found in "{self.repository}". Skipping GitHub Actions upgrade',
                message_type='warning'
            )
            return

        for workflow_path in workflow_paths:
            try:
                with open(workflow_path, 'r+') as file:
                    print_message(f'Checking "{workflow_path}" for updates....')

                    file_data = file.read()
                    updated_config = file_data

                    data = yaml.load(file_data, Loader=yaml.FullLoader)
                    old_action_set = set(self.get_all_actions(data))

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

                        updated_action = f'{action_repository}@{latest_release["tag_name"]}'

                        if action != updated_action:
                            print_message(
                                f'Found new version for "{action_repository}" on "{workflow_path}".'
                            )
                            comment += self.generate_comment_line(
                                action_repository, latest_release
                            )
                            print_message(
                                f'Updating "{action}" with "{updated_action}" on "{workflow_path}".'
                            )
                            updated_config = updated_config.replace(
                                action, updated_action
                            )
                            file.seek(0)
                            file.write(updated_config)
                            file.truncate()
                            self.workflow_updated = True
            except Exception:
                print_message(f'Skipping "{workflow_path}"')
                pass

        if self.workflow_updated:
            # Use timestamp to ensure uniqueness of the new branch
            new_branch = f'gh-action-upgrade-{int(time.time())}'

            print_message('Create New Branch', message_type='group')

            subprocess.run(
                ['git', 'checkout', self.base_branch]
            )
            subprocess.run(
                ['git', 'checkout', '-b', new_branch]
            )
            subprocess.run(['git', 'add', '.'])
            subprocess.run(
                ['git', 'commit', '-m', 'Upgrade GitHub Action Versions']
            )

            subprocess.run(['git', 'push', '-u', 'origin', new_branch])

            print_message('', message_type='endgroup')

            current_branch = subprocess.check_output(
                ['git', 'branch', '--show-current']
            )

            if new_branch in str(current_branch):
                print_message('Create Pull Request', message_type='group')

                self.create_pull_request(new_branch, comment)

                print_message('', message_type='endgroup')

    def create_pull_request(self, branch_name, body):
        """Create pull request on GitHub"""
        url = f'{self.github_api_url}/repos/{self.repository}/pulls'
        payload = {
            'title': 'Upgrade GitHub Action Versions',
            'head': branch_name,
            'base': self.base_branch,
            'body': '### GitHub Actions Version Upgrades\n' + body,
        }

        response = requests.post(
            url, json=payload, headers=self.get_request_headers()
        )

        if response.status_code == 201:
            html_url = response.json()['html_url']
            print_message(f'Creating pull request at {html_url}.')
        else:
            msg = (
                f'Could not create a pull request on '
                f'{self.repository}, status code: {response.status_code}'
            )
            print_message(msg, message_type='warning')

    def generate_comment_line(self, action_repository, latest_release):
        """Generate Comment line for pull request body"""
        return (
            f"* **[{action_repository}]({self.github_url + action_repository})** published a new release "
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
            print_message(msg, message_type='warning')

        return data

    def get_workflow_paths(self):
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
            print_message(msg, message_type='error')

        return data

    def get_all_actions(self, config):
        """Recursively get all action names from config"""
        if isinstance(config, dict):
            for key, value in config.items():
                if key == self.action_label:
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
    print_message('Configure Git', message_type='group')

    subprocess.run(['git', 'config', 'user.name', username])
    subprocess.run(['git', 'config', 'user.email', email])

    print_message('', message_type='endgroup')

    # Group: Generate Changelog
    print_message('Upgrade GitHub Actions', message_type='group')

    # Initialize the Changelog CI
    action_upgrade = GitHubActionUpgrade(
        repository, base_branch, token
    )
    action_upgrade.run()

    print_message('', message_type='endgroup')
