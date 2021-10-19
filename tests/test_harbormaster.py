from pathlib import Path
from typing import Dict

import pytest
from utils import Repository
from utils import run_harbormaster

from docker_harbormaster import cli

# Tarry not.
cli.RETRY_WAIT_SECONDS = 0
cli.MAX_GIT_NETWORK_ATTEMPTS = 1


@pytest.fixture()
def repos(tmp_path):
    """Set up the required repositories for the tests."""
    repos = {}

    # Create the app repo and add an app.
    repo = Repository("apps", tmp_path)
    repo.add_files(
        (("docker-compose.yml", "services:\n web:\n  image: app"),),
    )

    # Add app1.
    repo.checkout("app1")
    repo.add_files(
        (("docker-compose.yml", "services:\n web:\n  image: app"),),
    )

    repo.checkout("app2")
    repo.add_files(
        (("docker-compose.yml", "services:\n web:\n  image: app"),),
    )

    repos["apps"] = repo

    # Create the Harbormaster config repo.
    repos["config"] = Repository("config", tmp_path)
    repos["config"].add_files(
        (
            (
                "harbormaster.yml",
                f"""
                apps:
                  myapp:
                    url: {repos['apps'].path}
                """,
            ),
        ),
    )
    return repos


def test_one_app(tmp_path: Path, repos: Dict[str, Repository]):
    """Check a single-app scenario."""
    result, output = run_harbormaster(tmp_path, repos)

    assert result.exit_code == 0
    assert result.output
    assert output["commands"] == [
        "/usr/bin/env docker-compose -f docker-compose.yml ps --services --filter status=running",
        "/usr/bin/env docker-compose -f docker-compose.yml pull",
        "/usr/bin/env docker-compose -f docker-compose.yml up --remove-orphans --build -d",
    ]


def test_branches(tmp_path: Path, repos: Dict[str, Repository]):
    """Check the scenario where every app is a branch in the same repo."""
    # Create a config that runs apps in branches.
    repos["config"].add_files(
        (
            (
                "harbormaster.yml",
                f"""
                apps:
                  app1:
                    url: {repos['apps'].path}
                    branch: app1
                  app2:
                    url: {repos['apps'].path}
                    branch: app2
                """,
            ),
        ),
    )

    result, output = run_harbormaster(tmp_path, repos)

    assert result.exit_code == 0
    assert result.output
    assert output["clone_or_pull"] == {"app1": True, "app2": True}
    assert output["commands"] == [
        "/usr/bin/env docker-compose -f docker-compose.yml ps --services --filter status=running",
        "/usr/bin/env docker-compose -f docker-compose.yml pull",
        "/usr/bin/env docker-compose -f docker-compose.yml up --remove-orphans --build -d",
        "/usr/bin/env docker-compose -f docker-compose.yml ps --services --filter status=running",
        "/usr/bin/env docker-compose -f docker-compose.yml pull",
        "/usr/bin/env docker-compose -f docker-compose.yml up --remove-orphans --build -d",
    ]

    # Change the app in one branch and ensure the other one didn't restart.
    repos["apps"].checkout("app2")
    repos["apps"].add_files(
        (("test", "Whatever"),),
    )

    result, output = run_harbormaster(tmp_path, repos)

    assert result.exit_code == 0
    assert result.output
    assert output["clone_or_pull"] == {"app1": False, "app2": True}
    assert output["commands"] == [
        "/usr/bin/env docker-compose -f docker-compose.yml ps --services --filter status=running",
        "/usr/bin/env docker-compose -f docker-compose.yml pull",
        "/usr/bin/env docker-compose -f docker-compose.yml up --remove-orphans --build -d",
        "/usr/bin/env docker-compose -f docker-compose.yml ps --services --filter status=running",
        "/usr/bin/env docker-compose -f docker-compose.yml pull",
        "/usr/bin/env docker-compose -f docker-compose.yml up --remove-orphans --build -d",
    ]
