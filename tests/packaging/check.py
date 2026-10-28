"""Validate release metadata and exercise artifacts outside the checkout."""

import argparse
import email
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path

from packaging.requirements import Requirement
from pydantic import JsonValue, TypeAdapter

ROOT = Path(__file__).resolve().parents[2]
_STRING = TypeAdapter(str)
_STRING_LIST = TypeAdapter(list[str])


def project_version(root: Path = ROOT) -> str:
    """Read and validate the version from project metadata."""
    return _STRING.validate_python(
        tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"],
        strict=True,
    )


def validate_release(tag: str, root: Path = ROOT) -> str:
    """Require a release tag and action PyPI requirement matching the version."""
    version = project_version(root)
    if (
        not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:(?:a|b|rc)[0-9]+)?", tag)
        or tag != f"v{version}"
    ):
        raise ValueError(
            "Release tag must match the package version, including suffix."
        )
    pins = re.findall(
        r"update-gha\[action\]==([^\s'\"]+)", (root / "action.yaml").read_text()
    )
    if pins != [version]:
        raise ValueError("Action must pin exactly the released PyPI package version.")
    return version


def check(directory: Path) -> None:
    """Inspect wheel and sdist, then test fresh base and action installations."""
    version = project_version()
    directory = directory.resolve()
    artifacts = (
        directory / f"update_gha-{version}-py3-none-any.whl",
        directory / f"update_gha-{version}.tar.gz",
    )
    assert {p for p in directory.iterdir() if p.name != ".gitignore"} == set(
        artifacts
    ), "Unexpected release artifacts"
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    with zipfile.ZipFile(artifacts[0]) as wheel:
        names = {name for name in wheel.namelist() if not name.endswith("/")}
        expected_package = {
            path.relative_to(ROOT / "src").as_posix()
            for path in (ROOT / "src/update_gha").rglob("*")
            if path.suffix == ".py" or path.name == "py.typed"
        }
        assert {n for n in names if n.startswith("update_gha/")} == expected_package
        assert all(
            n.startswith(("update_gha/", f"update_gha-{version}.dist-info/"))
            for n in names
        )
        assert any(name.endswith("/LICENSE") for name in names)
        info = email.message_from_bytes(
            wheel.read(f"update_gha-{version}.dist-info/METADATA")
        )
        assert info["Name"] == "update-gha" and info["Version"] == version
        assert info["Requires-Python"] == project["requires-python"]
        assert info["License-Expression"] == "MIT"
        assert info["Description-Content-Type"] == "text/markdown"
        assert info.get_payload(decode=True) == (ROOT / "README.md").read_bytes()
        requirements = _STRING_LIST.validate_python(info.get_all("Requires-Dist", []))
        expected_requirements = {
            Requirement(item)
            for item in _STRING_LIST.validate_python(project["dependencies"])
        } | {
            Requirement(f"{item}; extra == 'action'")
            for item in _STRING_LIST.validate_python(
                project["optional-dependencies"]["action"]
            )
        }
        assert {Requirement(item) for item in requirements} == expected_requirements
        entry_points = wheel.read(
            f"update_gha-{version}.dist-info/entry_points.txt"
        ).decode()
        assert "update-gha = update_gha.cli:app" in entry_points
    with tarfile.open(artifacts[1]) as sdist:
        source_names = set(sdist.getnames())
        prefix = f"update_gha-{version}/"
        for name in (
            "README.md",
            "LICENSE",
            "pyproject.toml",
            "action.yaml",
            "uv.lock",
            "src/update_gha/py.typed",
            "tests/smoke_test.py",
            "tests/packaging/check.py",
        ):
            assert prefix + name in source_names, name
        assert not any(
            "__pycache__" in n or ".DS_Store" in n or "/.venv/" in n
            for n in source_names
        )
    clean_env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(
            ("GITHUB_", "GHA_UPDATE_", "INPUT_", "PYTHON", "UV_", "PIP_")
        )
        and key not in {"VIRTUAL_ENV", "CONDA_PREFIX", "GH_TOKEN"}
    }
    # Carry only the cache location into installation commands, never user indexes.
    install_env = clean_env | {
        "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", str(ROOT / ".tox/.uv-cache"))
    }
    with tempfile.TemporaryDirectory(prefix="update-gha-package-") as temporary:
        outside = Path(temporary)
        for index, artifact in enumerate(artifacts):
            for extra in ("", "[action]"):
                environment = outside / f"venv{index}{'action' if extra else 'base'}"
                subprocess.run(
                    [
                        "uv",
                        "--no-config",
                        "venv",
                        "--python",
                        sys.executable,
                        str(environment),
                    ],
                    cwd=outside,
                    env=install_env,
                    check=True,
                )
                scripts = environment / ("Scripts" if os.name == "nt" else "bin")
                python = scripts / ("python.exe" if os.name == "nt" else "python")
                console = scripts / (
                    "update-gha.exe" if os.name == "nt" else "update-gha"
                )
                subprocess.run(
                    [
                        "uv",
                        "--no-config",
                        "pip",
                        "install",
                        "--python",
                        str(python),
                        str(artifact) + extra,
                    ],
                    cwd=outside,
                    env=install_env,
                    check=True,
                )
                for command in (
                    [str(console)],
                    [str(python), "-I", "-m", "update_gha"],
                ):
                    result = subprocess.run(
                        [*command, "--version"],
                        cwd=outside,
                        env=clean_env,
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    assert result.stdout.strip() == version
                    help_result = subprocess.run(
                        [*command, "--help"],
                        cwd=outside,
                        env=clean_env,
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    assert "--pull-request" in help_result.stdout
                    result = subprocess.run(
                        [*command, "--dry-run", "--format", "json"],
                        cwd=outside,
                        env=clean_env
                        | {"GITHUB_ACTIONS": "true", "COMMANDS_USE_SUBPROCESS": "1"},
                        capture_output=True,
                        text=True,
                    )
                    if extra:
                        assert result.returncode == 0, result.stderr
                        assert TypeAdapter(JsonValue).validate_json(result.stdout) == {
                            "files": [],
                            "wrote": False,
                        }
                        assert "No workflow files found" in result.stderr
                    else:
                        assert result.returncode == 2, result.stderr
                        assert "Install the action extra" in result.stderr
                        assert "ModuleNotFoundError" not in result.stderr
                subprocess.run(
                    [
                        str(python),
                        "-I",
                        str(ROOT / "tests/smoke_test.py"),
                        "action" if extra else "base",
                    ],
                    cwd=outside,
                    env=clean_env,
                    check=True,
                )
    print("Wheel and sdist passed metadata, installation and entry point checks.")


def main() -> None:
    """Validate a release tag or distributions already built in a directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path, default=ROOT / "dist")
    parser.add_argument("--release")
    args = parser.parse_args()
    if args.release:
        print(validate_release(_STRING.validate_python(args.release)))
    else:
        check(TypeAdapter(Path).validate_python(args.directory))


if __name__ == "__main__":
    main()
