import tempfile
from unittest.mock import patch

import git
from click.testing import CliRunner

from docker_harbormaster import cli


def patched_run():
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


def test_one_app(tmp_path):
    hm_yml = f"""
            apps:
              myapp:
                # The git repository URL to clone.
                url: {tmp_path}
        """
    with (tmp_path / "harbormaster.yml").open("w") as hm_yml_file:
        hm_yml_file.write(hm_yml)

    dc_yml = """
            version: "3.9"
            services:
              web:
                build: .
                ports:
                  - "5000:5000"
              redis:
                image: "redis:alpine"
        """

    with (tmp_path / "docker-compose.yml").open("w") as hm_yml_file:
        hm_yml_file.write(dc_yml)

    r = git.Repo.init(tmp_path)
    r.index.add(["harbormaster.yml", "docker-compose.yml"])
    r.index.commit("initial commit")

    fn, commands = patched_run()
    with tempfile.TemporaryDirectory() as wdir, patch(
        "docker_harbormaster.cli._run_command_full", side_effect=fn
    ):
        runner = CliRunner()
        result = runner.invoke(
            cli.cli,
            [
                "--config",
                f"{tmp_path}/harbormaster.yml",
                "--working-dir",
                wdir,
            ],
        )

        assert result.exit_code == 0, result.output

        assert commands == [
            "/usr/bin/env docker-compose -f docker-compose.yml ps --services --filter status=running",
            "/usr/bin/env docker-compose -f docker-compose.yml pull",
            "/usr/bin/env docker-compose -f docker-compose.yml up --remove-orphans --build -d",
        ]
