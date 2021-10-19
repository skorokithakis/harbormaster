import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable
from typing import Tuple

import git

from docker_harbormaster import cli


def mkdir(path: Path) -> Path:
    """Create a directory out of a path and return that path."""
    path.mkdir(exist_ok=True)
    return path


@contextmanager
def chdir(path: Path):
    """Sets the cwd within the context."""
    origin = Path().absolute()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(origin)


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


def create_repository(
    path: Path,
    contents: Iterable[Tuple[str, str]],
    branch="master",
) -> git.Repo:
    """
    Create a repository with the specified contents.

    Contents should be an iterable of (filename, contents) tuples.
    """
    repo = git.Repo.init(path)
    repo.git.checkout(b=branch)
    with chdir(path):
        for filename, content in contents:
            with open(filename, "w") as outfile:
                outfile.write(content)
            repo.index.add(filename)
    repo.index.commit("Initial commit")
    return repo
