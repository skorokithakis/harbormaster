import os
import tempfile
from unittest.mock import patch

import git
from click.testing import CliRunner

from docker_harbormaster import cli


def test_one_app():
    with tempfile.TemporaryDirectory() as hdir:
        hm_yml = f"""
            apps:
              myapp:
                # The git repository URL to clone.
                url: {hdir}
        """
        with open(os.path.join(hdir, "harbormaster.yml"), "w") as hm_yml_file:
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

        with open(os.path.join(hdir, "docker-compose.yml"), "w") as hm_yml_file:
            hm_yml_file.write(dc_yml)

        r = git.Repo.init(hdir)
        r.index.add(["harbormaster.yml", "docker-compose.yml"])
        r.index.commit("initial commit")

        rcf = cli.run_command_full
        commands = []

        def patched_run(command, chdir, environment=None):
            if "docker-compose" in command:
                commands.append(" ".join(command))
                return 0, b"", b""
            else:
                return rcf(command, chdir, environment=environment)

        with tempfile.TemporaryDirectory() as wdir, patch(
            "docker_harbormaster.cli.run_command_full", side_effect=patched_run
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli.cli,
                [
                    "--config",
                    f"{hdir}/harbormaster.yml",
                    "--working-dir",
                    wdir,
                ],
            )

            assert result.exit_code == 0, result.output

            want_raw = """
                /usr/bin/env docker-compose -f docker-compose.yml ps --services --filter status=running
                /usr/bin/env docker-compose -f docker-compose.yml pull
                /usr/bin/env docker-compose -f docker-compose.yml up --remove-orphans --build -d
            """

            want = [
                line.strip() for line in want_raw.splitlines() if "/usr/bin/env" in line
            ]

            assert want == commands
