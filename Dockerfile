FROM python:3.12-slim-bullseye

LABEL "com.github.actions.name"="GitHub Actions Version Updater"
LABEL "com.github.actions.description"="GitHub Actions Version Updater updates GitHub Action versions in a repository and creates a pull request with the changes."
LABEL "com.github.actions.icon"="upload-cloud"
LABEL "com.github.actions.color"="green"

LABEL "repository"="https://github.com/saadmk11/github-actions-version-updater"
LABEL "homepage"="https://github.com/saadmk11/github-actions-version-updater"
LABEL "maintainer"="saadmk11"

RUN apt-get update \
    && apt-get install \
       -y \
       --no-install-recommends \
       --no-install-suggests \
       git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY ./requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . ./app

ENV PYTHONPATH "${PYTHONPATH}:/app"

CMD ["python", "-m", "src.main"]
