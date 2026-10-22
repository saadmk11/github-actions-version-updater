"""Exercise the installed distribution without contacting GitHub."""

from __future__ import annotations

import sys
import tempfile
from contextlib import chdir
from pathlib import Path
from unittest.mock import patch

import httpx
from pydantic import JsonValue, TypeAdapter
from typer.testing import CliRunner

import update_gha
from update_gha import __version__
from update_gha.action import has_action_extra
from update_gha.cli import app


def main() -> None:
    assert (
        Path(update_gha.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
    ), "Smoke checks must import the installed package"
    action_extra = len(sys.argv) > 1 and sys.argv[1] == "action"
    assert has_action_extra() is action_extra
    sha = "a" * 40
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.method == "GET"
        assert request.headers["Authorization"] == "Bearer test-token"
        match request.url.path:
            case "/repos/owner/action/releases":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "tag_name": "v2",
                            "html_url": "https://github.com/owner/action/releases/tag/v2",
                            "published_at": "2026-01-01T00:00:00Z",
                        }
                    ],
                )
            case "/repos/owner/action/commits":
                assert request.url.params["sha"] == "v2"
                return httpx.Response(
                    200,
                    json=[
                        {
                            "sha": sha,
                            "html_url": f"https://github.com/owner/action/commit/{sha}",
                            "commit": {"author": {"date": "2026-01-01T00:00:00Z"}},
                        }
                    ],
                )
            case _:
                raise AssertionError(f"Unexpected request: {request.url}")

    client_factory = httpx.Client

    def make_client(*, timeout: httpx.Timeout, follow_redirects: bool) -> httpx.Client:
        return client_factory(
            timeout=timeout,
            follow_redirects=follow_redirects,
            transport=httpx.MockTransport(respond),
        )

    runner = CliRunner()
    with (
        tempfile.TemporaryDirectory() as directory,
        chdir(directory),
    ):
        workflow = Path(".github/workflows/ci.yml")
        workflow.parent.mkdir(parents=True)
        original = (
            b"# Keep this comment\r\njobs:\r\n  build:\r\n    steps:\r\n"
            b"      - uses: 'owner/action@v1'\r\n"
        )
        workflow.write_bytes(original)
        with patch("update_gha.github.httpx.Client", make_client):
            result = runner.invoke(
                app,
                [
                    "--token",
                    "test-token",
                    "--update-version-with",
                    "release-commit-sha",
                    "--format",
                    "json",
                    "--no-pull-request",
                ],
            )
        assert result.exit_code == 0, result.output
        expected = original.replace(
            b"'owner/action@v1'", f"'owner/action@{sha}'  # v2".encode()
        )
        assert workflow.read_bytes() == expected
        report = TypeAdapter(dict[str, JsonValue]).validate_json(result.stdout)
        assert report["wrote"] is True
        assert isinstance(report["files"], list) and len(report["files"]) == 1
        assert len(seen) == 2

        result = runner.invoke(
            app,
            [
                "--pull-request",
                "--token",
                "test-token",
                "--repository",
                "owner/repo",
                "--pull-request-branch",
                "main",
            ],
        )
        if action_extra:
            assert result.exit_code == 1
            assert "Invalid pull_request_branch" in result.stderr
        else:
            assert result.exit_code == 2
            assert "Install the action extra" in result.stderr
    print(f"smoke ok {__version__}")


if __name__ == "__main__":
    main()
