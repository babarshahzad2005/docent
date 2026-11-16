"""Docent API."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("docent-api")
except PackageNotFoundError:  # running from source without the package installed
    __version__ = "0.0.0+source"
