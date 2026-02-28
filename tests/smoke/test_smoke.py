"""Smoke tests — run harden analyze on every example app and verify it doesn't crash."""

import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from harden.cli import main

EXAMPLES_DIR = Path(__file__).parent / "examples"


def _collect_apps():
    """Yield (app_id, app_path) for every example app directory."""
    for entry in sorted(EXAMPLES_DIR.iterdir()):
        if not entry.is_dir():
            continue
        # The synthetic/ directory contains nested app dirs
        if entry.name == "synthetic":
            for sub in sorted(entry.iterdir()):
                if sub.is_dir() and not sub.name.startswith("."):
                    yield f"synthetic/{sub.name}", sub
        else:
            yield entry.name, entry


APP_LIST = list(_collect_apps())


@pytest.mark.parametrize("app_id, app_path", APP_LIST, ids=[a[0] for a in APP_LIST])
def test_analyze_does_not_crash(app_id, app_path, tmp_path):
    """harden analyze should exit 0 on every example app."""
    # Work on a copy so we don't pollute the fixture with generated files
    project = tmp_path / app_path.name
    shutil.copytree(app_path, project)

    runner = CliRunner()
    result = runner.invoke(main, ["analyze", str(project)])
    assert result.exit_code == 0, (
        f"harden analyze failed on {app_id}:\n{result.output}\n{result.exception}"
    )
