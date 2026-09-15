"""Package version, read from the installed distribution metadata."""

from importlib.metadata import version

__version__ = version("update-gha")
