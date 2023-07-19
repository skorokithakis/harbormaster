import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from typing import Dict
from typing import Iterable
from typing import Set
from typing import Tuple
from unittest.mock import patch

import click
import git
from click.testing import CliRunner

from docker_harbormaster import cli


@contextmanager
def chdir(path: Path):
    """Sets the cwd within the context."""
    origin = Path().absolute()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(origin)


class Repository:
    def __init__(self, name: str, root_dir: Path, branch="master"):
        self._name = name
        self._root_dir = root_dir
        self._repo = git.Repo.init(root_dir / name)
        self.checkout(branch)

    @property
    def path(self) -> Path:
        """Return the path of the repo on disk."""
        return Path(str(self._repo.working_tree_dir))

    def add_files(self, contents: Iterable[Tuple[str, str]]) -> None:
        """Add a bunch of files to a repository and commit."""
        with chdir(self.path):
            for filename, content in contents:
                with open(filename, "w") as outfile:
                    outfile.write(content)
                self._repo.index.add(filename)
        self._repo.index.commit("Commit")

    def checkout(self, rev: str) -> None:
        """Check out a given revision."""
        refs = [x.name for x in self._repo.references]
        self._repo.git.checkout(rev, b=rev not in refs)


def mkdir(path: Path) -> Path:
    """Create a directory out of a path and return that path."""
    path.mkdir(exist_ok=True)
    return path


def _patched_run():
    """Mock _run_command_full so that we can get the commands."""
    rcf = cli._run_command_full

    commands = []

    def inner(command, chdir, environment=None, **kwargs):
        if "docker compose" in command:
            commands.append(" ".join(command))
            return 0, b""
        else:
            return rcf(command, chdir, environment=environment)

    # Return the patched _run_command_full and the list that will eventually hold the
    # commands.
    return inner, commands


def run_harbormaster(
    tmp_path: Path, repos: Dict[str, Repository]
) -> Tuple[Any, Dict[str, Any]]:
    """I'm terribly sorry about this, it was the only way."""
    rcf_mock, commands = _patched_run()
    fn_stop = cli.App.stop
    # Prepare a list of the functions' outputs.
    output: Dict[str, Set[str]] = {"restarted_apps": set()}

    def stop_mock(self, *args, **kwargs):
        """A stop() mock."""
        output["restarted_apps"].add(self.id)
        return fn_stop(self, *args, **kwargs)

    with patch("docker_harbormaster.cli._run_command_full", side_effect=rcf_mock):
        with patch.object(cli.App, "stop", stop_mock):
            runner = CliRunner()
            result = runner.invoke(
                cli.cli,
                [
                    "--debug",
                    "run",
                    "--config",
                    f"{repos['config'].path}/harbormaster.yml",
                    "--working-dir",
                    str(mkdir(tmp_path / "working_dir")),
                ],
            )
            click.echo(result.stdout)
    output["commands"] = commands
    return result, output
