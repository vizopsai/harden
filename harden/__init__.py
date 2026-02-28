"""Harden - Enterprise hardening tool for vibe-coded apps."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("harden")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"
