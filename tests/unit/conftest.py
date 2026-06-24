"""Shared test fixtures for uFawkesDORA unit tests."""

from pathlib import Path

import pytest


@pytest.fixture
def project_root():
    """Return the project root directory."""
    return Path(__file__).parent.parent.parent


@pytest.fixture
def github_dir(project_root):
    """Return the .github directory."""
    return project_root / ".github"


@pytest.fixture
def workflows_dir(github_dir):
    """Return the workflows directory."""
    return github_dir / "workflows"


@pytest.fixture
def workflow_files(workflows_dir):
    """Return all workflow files."""
    return list(workflows_dir.glob("*.yml")) + list(workflows_dir.glob("*.yaml"))
