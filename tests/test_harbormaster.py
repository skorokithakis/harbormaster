import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable
from typing import Tuple
from unittest.mock import patch

import git
from click.testing import CliRunner

from docker_harbormaster import cli


@contextmanager
def _chdir(path: Path):
    """Sets the cwd within the context."""
    origin = Path().absolute()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(origin)


def _patched_run():
    """Mock _run_command_full so that we can get the commands."""
    rcf = cli._run_command_full

    commands = []

    def inner(command, chdir, environment=None):
        if "docker-compose" in command:
            commands.append(" ".join(command))
            return 0, b"", b""
        else:
            return rcf(command, chdir, environment=environment)

    # Return the patched _run_command_full and the list that will eventually hold the
    # commands.
    return inner, commands


def create_repository(path: Path, contents: Iterable[Tuple[str, str]]):
    """
    Create a repository with the specified contents.

    Contents should be an iterable of (filename, contents) tuples.
    """
    repo = git.Repo.init(path)
    with _chdir(path):
        for filename, content in contents:
            with open(filename, "w") as outfile:
                outfile.write(content)
            repo.index.add(filename)
    repo.index.commit("Initial commit")


def test_one_app(tmp_path):
    create_repository(
        tmp_path / "harbormaster",
        (
            (
                "harbormaster.yml",
                f"""
                apps:
                  myapp:
                    url: {tmp_path}/harbormaster
                """,
            ),
            ("harbormaster2.yml", "hi"),
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

    fn, commands = _patched_run()
    working_dir = tmp_path / "working_dir"
    working_dir.mkdir()
    with patch("docker_harbormaster.cli._run_command_full", side_effect=fn):
        runner = CliRunner()
        result = runner.invoke(
            cli.cli,
            [
                "--config",
                f"{tmp_path}/harbormaster/harbormaster.yml",
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
