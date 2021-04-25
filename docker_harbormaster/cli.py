#!/usr/bin/env python3
import os
import shutil
import subprocess
from pathlib import Path
from time import strftime
from typing import Any
from typing import List
from typing import Set
from typing import Tuple

import click
import yaml

try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader  # type: ignore


DEBUG = False


def debug(message: Any) -> None:
    """Print a message if DEBUG is True."""
    if DEBUG:
        click.echo(message)


def run_command_full(command: List[str], chdir: Path) -> Tuple[int, bytes, bytes]:
    """Run a command and return its exit code, stdout, and stderr."""
    wd = os.getcwd()
    os.chdir(chdir)
    debug(" ".join([str(x) for x in command]))
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate()
    debug(stdout)
    os.chdir(wd)
    return (process.returncode, stdout, stderr)


def run_command(command: List[str], chdir: Path) -> int:
    """Run a command and return its exit code."""
    return run_command_full(command, chdir)[0]


class RepoManager:
    def __init__(self, working_dir: Path):
        self._working_dir = working_dir

    def is_repo(self, directory: Path) -> bool:
        """Check whether a given directory is a repository."""
        if not directory.exists():
            return False
        return (
            run_command(
                ["/usr/bin/env", "git", "rev-parse", "--show-toplevel"], directory
            )
            == 0
        )

    def _dir_from_id(self, repo_id: str):
        return self._working_dir / "repos" / repo_id

    def check_for_upstream_changes(self, repo_id: str, repo_url: str) -> bool:
        """
        Check upstream for changes and return True if there are some.
        """
        repo_dir = self._dir_from_id(repo_id)
        if (
            run_command(
                ["/usr/bin/env", "git", "remote", "set-url", "origin", repo_url],
                repo_dir,
            )
            != 0
        ):
            raise Exception("Could not set origin.")

        return (
            run_command(
                ["/usr/bin/env", "git", "diff", "--exit-code", "--no-patch", "origin"],
                repo_dir,
            )
            != 0
        )

    def start_docker(self, repo_id: str):
        repo_dir = self._dir_from_id(repo_id)
        if run_command(["/usr/bin/env", "docker-compose", "up", "-d"], repo_dir) != 0:
            raise Exception("Could not start the docker-compose container.")

    def stop_docker(self, repo_id: str):
        repo_dir = self._dir_from_id(repo_id)
        stdout = run_command_full(
            ["/usr/bin/env", "docker-compose", "ps", "-q"], repo_dir
        )[1]
        if not stdout:
            # `docker ps` returned nothing, ie nothing is running.
            return

        if run_command(["/usr/bin/env", "docker-compose", "down"], repo_dir) != 0:
            raise Exception("Could not stop the docker-compose container.")

    def restart_docker(self, repo_id: str):
        self.stop_docker(repo_id)
        self.start_docker(repo_id)

    def replace_config_vars(self, repo_id: str):
        pass

    def clone_repo(self, repo_id: str, repo_url: str) -> bool:
        """
        Clone a repository.

        Returns whether an update was done.
        """
        repo_dir = self._dir_from_id(repo_id)
        if (
            run_command(
                ["/usr/bin/env", "git", "clone", repo_url, repo_dir], self._working_dir
            )
            != 0
        ):
            raise Exception("Could not clone repository.")

        return True

    def pull_repo(self, repo_id: str, repo_url: str) -> bool:
        """
        Pull a repository.

        Returns whether an update was done.
        """
        repo_dir = self._dir_from_id(repo_id)
        if not self.check_for_upstream_changes(repo_dir, repo_url):
            # No fetching/update necessary.
            return False

        if run_command(["/usr/bin/env", "git", "fetch", "--force"], repo_dir) != 0:
            raise Exception("Could not fetch from origin.")

        if (
            run_command(["/usr/bin/env", "git", "reset", "--hard", "origin"], repo_dir)
            != 0
        ):
            raise Exception("Could not reset local repository.")

        return True

    def clone_or_pull_repo(self, repo_id: str, repo_url: str) -> bool:
        """Pull a repository, or clone it if it hasn't been initialized yet."""
        repo_dir = self._dir_from_id(repo_id)
        if self.is_repo(repo_dir):
            click.echo(f"Pulling {repo_url} to {repo_dir}...")
            return self.pull_repo(repo_dir, repo_url)
        else:
            click.echo(f"Cloning {repo_url} to {repo_dir}...")
            return self.clone_repo(repo_dir, repo_url)


def process_config(configuration: Any, working_dir: Path):
    """Process a given configuration file."""
    rm = RepoManager(working_dir)
    for repo_id, repo_config in configuration["repositories"].items():
        click.echo(f"Updating {repo_id}...")
        try:
            if not rm.clone_or_pull_repo(repo_id=repo_id, repo_url=repo_config["url"]):
                click.echo("Repository does not need updating.\n")
                continue

            rm.replace_config_vars(repo_id=repo_id)
            click.echo(f"Starting {repo_id}...")
            rm.restart_docker(repo_id=repo_id)
        except Exception as e:
            click.echo(f"Error while processing {repo_id}: {e}")
        click.echo("")


def archive_stale_data(app_names: Set[str], working_dir: Path):
    current_repos = set(x.name for x in (working_dir / "repos").iterdir() if x.is_dir())
    current_data = set(x.name for x in (working_dir / "data").iterdir() if x.is_dir())

    rm = RepoManager(working_dir)
    for stale_repo in current_repos - app_names:
        path = working_dir / "repos" / stale_repo
        click.echo(
            f"The repo for {stale_repo} is stale, stopping any running containers..."
        )
        rm.stop_docker(repo_id=stale_repo)
        click.echo(f"Removing {path}...")
        shutil.rmtree(path)

    for stale_data in current_data - app_names:
        path = working_dir / "data" / stale_data
        click.echo(f"The data for {stale_data} is stale, archiving {path}...")
        path.rename(
            working_dir / "archives" / f"{stale_data}-{strftime('%Y-%m-%d_%H-%M-%S')}"
        )


@click.command()
@click.option(
    "-c",
    "--config",
    default="config.yaml",
    type=click.File("r"),
    help="The configuration file to use.",
)
@click.option(
    "-d",
    "--working_dir",
    default=".",
    type=click.Path(
        exists=True,
        file_okay=False,
        readable=True,
        writable=True,
        resolve_path=True,
    ),
    help="The root directory to work in.",
)
@click.option("--debug", is_flag=True, help="Print debug information.")
def cli(config, working_dir: str, debug: bool):
    global DEBUG
    DEBUG = debug

    workdir = Path(working_dir)
    for directory in ("repos", "data", "archives"):
        # Create the necessary directories.
        (workdir / directory).mkdir(exist_ok=True)

    configuration = yaml.load(config, Loader=Loader)
    archive_stale_data(set(configuration["repositories"].keys()), workdir)
    process_config(configuration, workdir)


if __name__ == "__main__":
    cli()
