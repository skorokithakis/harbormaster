from unittest.mock import patch

import pytest
from click.testing import CliRunner
from utils import create_repository
from utils import patched_run

from docker_harbormaster import cli


@pytest.fixture()
def repos(tmp_path):
    """Set up the required repositories for the tests."""
    repos = {}
    # Create the app repo.
    repos["app1"] = create_repository(
        tmp_path / "app1",
        (
            (
                "docker-compose.yml",
                """
                version: "3.9"
                services:
                  web:
                    build: .
                    ports:
                      - "5000:5000"
                  redis:
                    image: "redis:alpine"
                """,
            ),
        ),
    )

    # Create the Harbormaster config repo.
    repos["config"] = create_repository(
        tmp_path / "harbormaster",
        (
            (
                "harbormaster.yml",
                f"""
                apps:
                  myapp:
                    url: {tmp_path}/app1/
                """,
            ),
        ),
    )
    return repos


def test_one_app(tmp_path, repos):
    fn, commands = patched_run()
    working_dir = tmp_path / "working_dir"
    working_dir.mkdir()
    with patch("docker_harbormaster.cli._run_command_full", side_effect=fn):
        runner = CliRunner()
        result = runner.invoke(
            cli.cli,
            [
                "--config",
                f"{repos['config'].working_tree_dir}/harbormaster.yml",
                "--working-dir",
                str(working_dir),
            ],
        )

        assert result.exit_code == 0, result.output

        assert commands == [
            "/usr/bin/env docker-compose -f docker-compose.yml ps --services --filter status=running",
            "/usr/bin/env docker-compose -f docker-compose.yml pull",
            "/usr/bin/env docker-compose -f docker-compose.yml up --remove-orphans --build -d",
        ]
