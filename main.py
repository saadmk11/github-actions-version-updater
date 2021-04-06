import requests
import yaml


class GitHubActionUpgrade:

    github_api_url = 'https://api.github.com'
    action_label = 'uses'

    def __init__(self, token=None):
        self.token = token

    def run(self):
        url = ''

        response = requests.get(url)
        data = yaml.load(response.text, Loader=yaml.FullLoader)

        action_set = set(self.get_all_actions(data))
        new_action_set = set()

        for old_action in action_set:
            action_path, version = old_action.split('@')
            print('old: ', old_action)

            url = f'{self.github_api_url}/repos/{action_path}/releases/latest'
            response = requests.get(url)
            latest_release_tag = response.json()['tag_name']

            updated_action = f'{action_path}@{latest_release_tag}'
            print('new: ', updated_action)

            if old_action != updated_action:
                new_action_set.add(updated_action)

        print(action_set)
        print(new_action_set)

    def get_all_actions(self, config):
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


if __name__ == '__main__':
    a = GitHubActionUpgrade()
    a.run()
