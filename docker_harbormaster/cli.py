#!/usr/bin/env python3
import os
import shutil
import subprocess
from pathlib import Path
from time import strftime
from typing import Any
from typing import Dict
from typing import List
from typing import Tuple

import click
import yaml

try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader  # type: ignore


DEBUG: bool = False
WORKDIR: Path = Path(".")


def debug(message: Any) -> None:
    """Print a message if DEBUG is True."""
    if DEBUG:
        click.echo(message)


class Repository:
    def __init__(self, id: str, configuration: Dict[str, str]):
        self.id = id
        self.url = configuration["url"]
        self.compose_filename = configuration.get(
            "compose_filename", "docker-compose.yml"
        )
        self.branch = configuration.get("branch", "master")

    @property
    def dir(self):
        return WORKDIR / "repos" / self.id

    def is_repo(self) -> bool:
        """Check whether a repository exists and is actually a repository."""
        if not self.dir.exists():
            return False

        return (
            run_command(
                ["/usr/bin/env", "git", "rev-parse", "--show-toplevel"], self.dir
            )
            == 0
        )

    def clone(self) -> bool:
        """
        Clone a repository.

        Returns whether an update was done.
        """
        if (
            run_command(
                ["/usr/bin/env", "git", "clone", "-b", self.branch, self.url, self.dir],
                WORKDIR,
            )
            != 0
        ):
            raise Exception("Could not clone repository.")

        return True

    def pull(self) -> bool:
        """
        Pull a repository.

        Returns whether an update was done.
        """
        if not self.check_for_upstream_changes():
            # No update necessary.
            return False

        if run_command(["/usr/bin/env", "git", "reset", "--hard"], self.dir) != 0:
            raise Exception("Could not reset local repository.")

        if run_command(["/usr/bin/env", "git", "merge", "FETCH_HEAD"], self.dir) != 0:
            raise Exception("Could not check out given branch.")

        return True

    def check_for_upstream_changes(self) -> bool:
        """
        Check upstream for changes and return True if there are some.
        """
        if (
            run_command(
                ["/usr/bin/env", "git", "remote", "set-url", "origin", self.url],
                self.dir,
            )
            != 0
        ):
            raise Exception("Could not set origin.")

        if (
            run_command(
                ["/usr/bin/env", "git", "fetch", "--force", "origin", self.branch],
                self.dir,
            )
            != 0
        ):
            raise Exception("Could not fetch from origin.")

        a = (
            run_command_full(
                ["/usr/bin/env", "git", "rev-parse", self.branch], self.dir
            )[1]
            .decode()
            .strip()
        )
        b = (
            run_command_full(
                ["/usr/bin/env", "git", "rev-parse", f"origin/{self.branch}"], self.dir
            )[1]
            .decode()
            .strip()
        )

        # If the two revs are the same, we're up to date.
        return a != b

    def clone_or_pull(self) -> bool:
        """Pull a repository, or clone it if it hasn't been initialized yet."""
        if self.is_repo():
            click.echo(f"Pulling {self.url} to {self.dir}...")
            return self.pull()
        else:
            click.echo(f"Cloning {self.url} to {self.dir}...")
            return self.clone()


def run_command_full(command: List[str], chdir: Path) -> Tuple[int, bytes, bytes]:
    """Run a command and return its exit code, stdout, and stderr."""
    wd = os.getcwd()
    os.chdir(chdir)
    debug("Command: " + " ".join([str(x) for x in command]))
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate()
    debug(f"Return code: {process.returncode}")
    debug(stdout)
    debug(stderr)
    os.chdir(wd)
    return (process.returncode, stdout, stderr)


def run_command(command: List[str], chdir: Path) -> int:
    """Run a command and return its exit code."""
    return run_command_full(command, chdir)[0]


class RepoManager:
    def start_docker(self, repo: Repository):
        if (
            run_command(
                [
                    "/usr/bin/env",
                    "docker-compose",
                    "-f",
                    repo.compose_filename,
                    "up",
                    "-d",
                ],
                repo.dir,
            )
            != 0
        ):
            raise Exception("Could not start the docker-compose container.")

    def stop_docker(self, repo_id: str):
        """
        Stop all Docker containers for a repository.

        Instead of issuing `docker-compose down`, this method looks for all
        running containers that start with "{repo_id}_" (that's why it accepts
        a string instead of a Repository instance).

        That's because the configuration file might be missing, and we might
        not know what the compose file's name is.
        """
        stdout = run_command_full(
            ["/usr/bin/env", "docker", "ps", "-qf", f"name={repo_id}_"],
            Path("."),
        )[1]
        if not stdout:
            # `docker ps` returned nothing, ie nothing is running.
            return

        container_ids = stdout.decode().strip().split("\n")
        return_codes = []
        for container_id in container_ids:
            debug(f"Stopping container {container_id}...")
            return_codes.append(
                run_command(["/usr/bin/env", "docker", "stop", container_id], Path("."))
            )

        if any(return_codes):
            raise Exception("Could not stop some containers.")

    def restart_docker(self, repo: Repository):
        self.stop_docker(repo.id)
        self.start_docker(repo)

    def replace_config_vars(self, repo: Repository):
        with (repo.dir / repo.compose_filename).open("r+b") as cfile:
            contents = cfile.read()
            contents = contents.replace(
                b"{{ HM_DATA_DIR }}", str(WORKDIR / "data" / repo.id).encode()
            )
            contents = contents.replace(
                b"{{ HM_CACHE_DIR }}",
                str(WORKDIR / "caches" / repo.id).encode(),
            )
            cfile.truncate(0)
            cfile.seek(0)
            cfile.write(contents)


def process_config(repos: List[Repository]):
    """Process a given configuration file."""
    rm = RepoManager()
    for repo in repos:
        click.echo(f"Updating {repo.id} ({repo.branch})...")
        try:
            if not repo.clone_or_pull():
                click.echo("Repository does not need updating.\n")
                continue

            rm.replace_config_vars(repo)
            click.echo(f"(Re)starting {repo.id}...")
            rm.restart_docker(repo)
        except Exception as e:
            click.echo(f"Error while processing {repo.id}: {e}")
        click.echo("")


def archive_stale_data(repos: List[Repository]):
    app_names = set(repo.id for repo in repos)

    current_repos = set(x.name for x in (WORKDIR / "repos").iterdir() if x.is_dir())
    current_data = set(x.name for x in (WORKDIR / "data").iterdir() if x.is_dir())
    current_caches = set(x.name for x in (WORKDIR / "caches").iterdir() if x.is_dir())

    rm = RepoManager()
    for stale_repo in current_repos - app_names:
        path = WORKDIR / "repos" / stale_repo
        click.echo(
            f"The repo for {stale_repo} is stale, stopping any running containers..."
        )
        rm.stop_docker(stale_repo)
        click.echo(f"Removing {path}...")
        shutil.rmtree(path)

    for stale_data in current_data - app_names:
        path = WORKDIR / "data" / stale_data
        click.echo(f"The data for {stale_data} is stale, archiving {path}...")
        path.rename(
            WORKDIR / "archives" / f"{stale_data}-{strftime('%Y-%m-%d_%H-%M-%S')}"
        )

    for stale_caches in current_caches - app_names:
        path = WORKDIR / "caches" / stale_caches
        click.echo(f"The cache for {stale_caches} is stale, deleting {path}...")
        shutil.rmtree(path)


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
@click.version_option()
def cli(config, working_dir: str, debug: bool):
    global DEBUG, WORKDIR
    DEBUG = debug
    WORKDIR = Path(working_dir)

    for directory in ("archives", "caches", "data", "repos"):
        # Create the necessary directories.
        (WORKDIR / directory).mkdir(exist_ok=True)

    configuration = yaml.load(config, Loader=Loader)
    repos = [
        Repository(id=repo_id, configuration=repo_config)
        for repo_id, repo_config in configuration["repositories"].items()
    ]
    archive_stale_data(repos)
    process_config(repos)


if __name__ == "__main__":
    cli()
