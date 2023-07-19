import random
from pathlib import Path
from typing import Dict

import pytest
from utils import Repository
from utils import run_harbormaster

from docker_harbormaster import cli

# Tarry not.
cli.RETRY_WAIT_SECONDS = 0
cli.MAX_GIT_NETWORK_ATTEMPTS = 1

cli.DEBUG = True


@pytest.fixture()
def repos(tmp_path):
    """Set up the required repositories for the tests."""
    repos = {}

    def dockerfile():
        # We need to add a random number in the Dockerfile, otherwise git produces the
        # exact same hashes for both repos, probably because it only considers seconds
        # for the timestamps.
        return (
            (
                "docker-compose.yml",
                f"""
---
services:
  web:
    image: app
    random_number: {random.random()}
    volumes:
      - {{ HM_DATA_DIR }}/data:/data
""",
            ),
        )

    # Create the app repo and add an app.
    repo = Repository("apps", tmp_path)
    repo.add_files(dockerfile())
    # Add app1.
    repo.checkout("app1")
    repo.add_files(dockerfile())
    # Add app2.
    repo.checkout("app2")
    repo.add_files(dockerfile())
    repos["apps"] = repo

    # Create another app repo and add an app.
    repo = Repository("apps2", tmp_path)
    repo.add_files(dockerfile())
    # Add app1.
    repo.checkout("app1")
    repo.add_files(dockerfile())
    # Add app2.
    repo.checkout("app2")
    repo.add_files(dockerfile())
    repos["apps2"] = repo

    # Create the Harbormaster config repo.
    repos["config"] = Repository("config", tmp_path)
    repos["config"].add_files(
        (
            (
                "harbormaster.yml",
                f"""
---
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
        "/usr/bin/env docker compose -f docker-compose.yml ps --services --filter status=running",
        "/usr/bin/env docker compose -f docker-compose.yml pull",
        "/usr/bin/env docker compose -f docker-compose.yml up --remove-orphans --build --detach",
    ]


def test_env_changes(tmp_path: Path, repos: Dict[str, Repository]):
    """Check a single-app scenario."""
    repos["config"].add_files(
        (
            (
                "harbormaster.yml",
                f"""
---
apps:
  myapp:
    url: {repos['apps'].path}
""",
            ),
        ),
    )
    result, output = run_harbormaster(tmp_path, repos)

    assert result.exit_code == 0
    assert result.output
    assert output["restarted_apps"] == {"myapp"}
    assert output["commands"] == [
        "/usr/bin/env docker compose -f docker-compose.yml ps --services --filter status=running",
        "/usr/bin/env docker compose -f docker-compose.yml pull",
        "/usr/bin/env docker compose -f docker-compose.yml up --remove-orphans --build --detach",
    ]

    repos["config"].add_files(
        (
            (
                "harbormaster.yml",
                f"""
---
apps:
  myapp:
    url: {repos['apps'].path}
    environment:
      foo: bar
""",
            ),
        ),
    )

    assert result.exit_code == 0
    assert result.output
    assert output["restarted_apps"] == {"myapp"}
    assert output["commands"] == [
        "/usr/bin/env docker compose -f docker-compose.yml ps --services --filter status=running",
        "/usr/bin/env docker compose -f docker-compose.yml pull",
        "/usr/bin/env docker compose -f docker-compose.yml up --remove-orphans --build --detach",
    ]

    result, output = run_harbormaster(tmp_path, repos)
    assert result.exit_code == 0
    assert output["restarted_apps"] == {"myapp"}

    repos["config"].add_files(
        (
            (
                "harbormaster.yml",
                f"""
---
apps:
  myapp:
    url: {repos['apps'].path}
    environment:
      foo: bar
      baz: hello
  app1:
    url: {repos['apps'].path}
    branch: app1
""",
            ),
        ),
    )

    result, output = run_harbormaster(tmp_path, repos)
    assert result.exit_code == 0
    assert output["restarted_apps"] == {"myapp", "app1"}

    repos["config"].add_files(
        (
            (
                "harbormaster.yml",
                f"""
---
apps:
  myapp:
    url: {repos['apps'].path}
    environment:
      foo: bar
      baz: hello
    replacements:
      hi: there
  app1:
    url: {repos['apps'].path}
    branch: app1
""",
            ),
        ),
    )

    result, output = run_harbormaster(tmp_path, repos)
    assert result.exit_code == 0
    assert output["restarted_apps"] == {"myapp"}


def test_branches(tmp_path: Path, repos: Dict[str, Repository]):
    """Check the scenario where every app is a branch in the same repo."""
    # Create a config that runs apps in branches.
    repos["config"].add_files(
        (
            (
                "harbormaster.yml",
                f"""
---
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
    assert output["restarted_apps"] == {"app1", "app2"}

    # Change the app in one branch and ensure the other one didn't restart.
    repos["apps"].checkout("app2")
    repos["apps"].add_files(
        (("test", "Whatever"),),
    )

    result, output = run_harbormaster(tmp_path, repos)

    assert result.exit_code == 0
    assert result.output
    assert output["restarted_apps"] == {"app2"}


def test_changing_remotes(tmp_path: Path, repos: Dict[str, Repository]):
    repos["config"].add_files(
        (
            (
                "harbormaster.yml",
                f"""
---
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
    assert output["restarted_apps"] == {"app1", "app2"}

    # Change remotes.
    repos["config"].add_files(
        (
            (
                "harbormaster.yml",
                f"""
---
apps:
  app1:
    url: {repos['apps2'].path}
    branch: app1
  app2:
    url: {repos['apps2'].path}
    branch: app2
""",
            ),
        ),
    )

    result, output = run_harbormaster(tmp_path, repos)

    assert result.exit_code == 0
    assert result.output
    assert output["restarted_apps"] == {"app1", "app2"}


def test_changing_branches(tmp_path: Path, repos: Dict[str, Repository]):
    repos["config"].add_files(
        (
            (
                "harbormaster.yml",
                f"""
---
apps:
  app1:
    url: {repos['apps'].path}
""",
            ),
        ),
    )

    result, output = run_harbormaster(tmp_path, repos)

    assert result.exit_code == 0
    assert result.output
    assert output["restarted_apps"] == {"app1"}

    # Change remotes.
    repos["config"].add_files(
        (
            (
                "harbormaster.yml",
                f"""
---
apps:
  app1:
    url: {repos['apps'].path}
    branch: app1
""",
            ),
        ),
    )

    result, output = run_harbormaster(tmp_path, repos)

    assert result.exit_code == 0
    assert result.output
    assert output["restarted_apps"] == {"app1"}


def test_changing_any_configs(tmp_path: Path, repos: Dict[str, Repository]):
    repos["config"].add_files(
        (
            (
                "harbormaster.yml",
                f"""
---
apps:
  app1:
    url: {repos['apps'].path}
""",
            ),
        ),
    )

    result, output = run_harbormaster(tmp_path, repos)

    assert result.exit_code == 0
    assert result.output
    assert output["restarted_apps"] == {"app1"}

    # add a commented-out line in harbormaster.yml -> no change
    repos["config"].add_files(
        (
            (
                "harbormaster.yml",
                f"""
---
apps:
  app1:
    #enabled: true
    url: {repos['apps'].path}
""",
            ),
        ),
    )

    result, output = run_harbormaster(tmp_path, repos)

    assert result.exit_code == 0
    assert result.output
    assert output["restarted_apps"] == set()

    # add a line in harbormaster.yml -> update then reboot
    repos["config"].add_files(
        (
            (
                "harbormaster.yml",
                f"""
---
apps:
  app1:
    enabled: true
    url: {repos['apps'].path}
""",
            ),
        ),
    )

    result, output = run_harbormaster(tmp_path, repos)

    assert result.exit_code == 0
    assert result.output
    assert output["restarted_apps"] == {"app1"}
