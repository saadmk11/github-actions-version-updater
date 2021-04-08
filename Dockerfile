FROM python:3.8

LABEL "com.github.actions.name"="GitHub Actions Version Updater"
LABEL "com.github.actions.description"="GitHub Actions Version Updater updates GitHub Action versions in a repository and creates a pull request with the changes."
LABEL "com.github.actions.icon"="upload-cloud"
LABEL "com.github.actions.color"="green"

LABEL "repository"="https://github.com/saadmk11/github-actions-version-updater"
LABEL "homepage"="https://github.com/saadmk11/github-actions-version-updater"
LABEL "maintainer"="saadmk11"

COPY requirements.txt /requirements.txt

RUN pip install -r requirements.txt

COPY main.py /main.py

RUN ["chmod", "+x", "/main.py"]
ENTRYPOINT ["python", "/main.py"]
