#!/usr/bin/env python3
import os
import re
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


class App:
    def __init__(self, id: str, configuration: Dict[str, Any]):
        self.id: str = id
        self.enabled: bool = configuration.get("enabled", True)
        self.url: str = configuration["url"]
        self.compose_filename: str = configuration.get(
            "compose_filename", "docker-compose.yml"
        )
        self.branch: str = configuration.get("branch", "master")
        self.environment: Dict[str, str] = configuration.get("environment", {})
        self.replacements: Dict[str, str] = configuration.get("replacements", {})

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

        if (
            run_command(
                ["/usr/bin/env", "git", "reset", "--hard", f"origin/{self.branch}"],
                self.dir,
            )
            != 0
        ):
            raise Exception("Could not reset local repository to the origin.")

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


def run_command_full(
    command: List[str], chdir: Path, environment: Dict[str, str] = None
) -> Tuple[int, bytes, bytes]:
    """Run a command and return its exit code, stdout, and stderr."""
    # Include the environment in our command.
    env = os.environ.copy()
    if environment:
        env.update(environment)

    wd = os.getcwd()
    os.chdir(chdir)
    debug("Command: " + " ".join([str(x) for x in command]))
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
    )
    stdout, stderr = process.communicate()
    debug(f"Return code: {process.returncode}")
    debug(stdout)
    debug(stderr)
    os.chdir(wd)
    return (process.returncode, stdout, stderr)


def run_command(
    command: List[str], chdir: Path, environment: Dict[str, str] = None
) -> int:
    """Run a command and return its exit code."""
    return run_command_full(command, chdir, environment=environment)[0]


class AppManager:
    def start_docker(self, app: App, environment: Dict[str, str]):
        if (
            run_command(
                [
                    "/usr/bin/env",
                    "docker-compose",
                    "-f",
                    app.compose_filename,
                    "up",
                    "--remove-orphans",
                    "-d",
                ],
                app.dir,
                environment=environment,
            )
            != 0
        ):
            raise Exception("Could not start the docker-compose container.")

    def stop_docker(self, repo: App):
        """
        Kill all Docker containers for an app.

        Instead of issuing `docker-compose down`, this method looks for all
        running containers that start with "{repo_id}_" (that's why it accepts
        a string instead of an App instance).

        That's because the configuration file might be missing, and we might
        not know what the compose file's name is.
        """
        stdout = run_command_full(
            ["/usr/bin/env", "docker-compose", "ps", "-q"], repo.dir
        )[1]

        if not stdout:
            # `docker ps` returned nothing, ie nothing is running.
            return

        if (
            run_command(
                ["/usr/bin/env", "docker-compose", "down", "--remove-orphans"], repo.dir
            )
            != 0
        ):
            raise Exception("Could not stop the docker-compose container.")

    def kill_orphan_containers(self, repo_id: str):
        """
        Stop all Docker containers for an app.

        Instead of issuing a `docker-compose down`, this method looks for all
        running containers that start with "{repo_id}_" (that's why it accepts
        a string instead of an App instance).

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

    def restart_docker(self, app: App):
        self.stop_docker(app)
        if app.enabled:
            self.start_docker(app, environment=app.environment)
        else:
            click.echo(f"{app.id} is disabled, will not run.")

    def replace_config_vars(self, app: App):
        with (app.dir / app.compose_filename).open("r+b") as cfile:
            contents = cfile.read()

            replacements = {
                "DATA_DIR": str(WORKDIR / "data" / app.id),
                "CACHE_DIR": str(WORKDIR / "caches" / app.id),
            }
            replacements.update(app.replacements)
            for varname, replacement in replacements.items():
                contents = re.sub(
                    (r"{{\s*HM_%s\s*}}" % varname).encode(),
                    replacement.encode(),
                    contents,
                )

            cfile.truncate(0)
            cfile.seek(0)
            cfile.write(contents)


def process_config(apps: List[App], force_restart: bool = False):
    """Process a given configuration file."""
    rm = AppManager()
    for app in apps:
        click.echo(f"Updating {app.id} ({app.branch})...")
        try:
            if not (app.clone_or_pull() or force_restart):
                click.echo("App does not need updating.\n")
                continue

            rm.replace_config_vars(app)
            click.echo(f"(Re)starting {app.id}...")
            rm.restart_docker(app)
        except Exception as e:
            click.echo(f"Error while processing {app.id}: {e}")
        click.echo("")


def archive_stale_data(repos: List[App]):
    app_names = set(repo.id for repo in repos)

    current_repos = set(x.name for x in (WORKDIR / "repos").iterdir() if x.is_dir())
    current_data = set(x.name for x in (WORKDIR / "data").iterdir() if x.is_dir())
    current_caches = set(x.name for x in (WORKDIR / "caches").iterdir() if x.is_dir())

    rm = AppManager()
    for stale_repo in current_repos - app_names:
        path = WORKDIR / "repos" / stale_repo
        click.echo(
            f"The repo for {stale_repo} is stale, stopping any running containers..."
        )
        rm.kill_orphan_containers(stale_repo)
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
    default="harbormaster.yml",
    type=click.File("r"),
    help="The configuration file to use.",
)
@click.option(
    "-d",
    "--working-dir",
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
@click.option(
    "-f",
    "--force-restart",
    is_flag=True,
    help="Restart all apps even if their repositories have not changed.",
)
@click.option("--debug", is_flag=True, help="Print debug information.")
@click.version_option()
def cli(config, working_dir: str, force_restart: bool, debug: bool):
    global DEBUG, WORKDIR
    DEBUG = debug
    WORKDIR = Path(working_dir)

    for directory in ("archives", "caches", "data", "repos"):
        # Create the necessary directories.
        (WORKDIR / directory).mkdir(exist_ok=True)

    configuration = yaml.load(config, Loader=Loader)
    apps = [
        App(id=repo_id, configuration=repo_config)
        for repo_id, repo_config in configuration["apps"].items()
    ]
    archive_stale_data(apps)
    process_config(apps, force_restart=force_restart)


if __name__ == "__main__":
    cli()
