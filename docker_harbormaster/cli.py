#!/usr/bin/env python3
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from time import strftime
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

import click
import yaml

try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader  # type: ignore


DEBUG: bool = False

ARCHIVES_DIR_NAME = "archives"
REPOS_DIR_NAME = "repos"
CACHES_DIR_NAME = "caches"
DATA_DIR_NAME = "data"


def debug(message: Any) -> None:
    """Print a message if DEBUG is True."""
    if DEBUG:
        click.echo(message)


class App:
    def __init__(
        self,
        id: str,
        configuration: Dict[str, Any],
        config_filename: Path,
        workdir: Path,
    ):
        self.id: str = id
        self.enabled: bool = configuration.get("enabled", True)
        self.url: str = configuration["url"]
        self.compose_filename: str = configuration.get(
            "compose_filename", "docker-compose.yml"
        )
        self.branch: str = configuration.get("branch", "master")
        self.workdir = workdir

        self.environment: Dict[str, str] = self._read_var_file(
            configuration.get("environment_file"), config_filename.parent
        )
        self.environment.update(
            {
                key: str(value)
                for key, value in configuration.get("environment", {}).items()
            }
        )

        self.replacements: Dict[str, str] = self._read_var_file(
            configuration.get("replacements_file", {}), config_filename.parent
        )
        self.replacements.update(
            {
                key: str(value)
                for key, value in configuration.get("replacements", {}).items()
            }
        )

    @property
    def dir(self):
        return self.workdir / REPOS_DIR_NAME / self.id

    def _read_var_file(self, filename: Optional[str], base_dir: Path) -> Dict[str, str]:
        """
        Read and parse an environment or replacements file.

        Abruptly terminates the program with an error message if the file could
        not be read.
        """
        if not filename:
            return {}

        f = (base_dir / Path(filename)).resolve()
        if not f.is_file():
            sys.exit(
                f'Environment or replacements file for app "{self.id}" '
                f"cannot be read, cannot continue:\n{f}"
            )
        output = {}
        contents = f.read_text()
        for line in contents.split("\n"):
            if not line:
                continue
            if "=" not in line:
                sys.exit(
                    f"Environment or replacements file for app {self.id} contained a "
                    f"line without an equals sign (=), cannot continue:\n{f}"
                )
            key, value = line.split("=", maxsplit=1)
            output[key] = value
        return output

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

    def is_running(self) -> bool:
        """Check if the app is running."""
        stdout = run_command_full(
            [
                "/usr/bin/env",
                "docker-compose",
                "-f",
                self.compose_filename,
                "ps",
                "--services",
                "--filter",
                "status=running",
            ],
            self.dir,
        )[1].strip()

        if stdout:
            debug(f"{self.id} is running.")
        else:
            debug(f"{self.id} is NOT running.")
        # If `docker ps` returned nothing, nothing is running.
        return bool(stdout)

    def start(self):
        """Start the Docker containers for this app."""
        status, stdout, stderr = run_command_full(
            [
                "/usr/bin/env",
                "docker-compose",
                "-f",
                self.compose_filename,
                "up",
                "--remove-orphans",
                "--build",
                "-d",
            ],
            self.dir,
            environment=self.environment,
        )

        if status != 0:
            raise Exception(
                f"Could not start the docker-compose container:\n{stderr.decode()}"
            )

    def stop(self):
        if not self.is_running():
            # `docker ps` returned nothing, ie nothing is running.
            return

        if (
            run_command(
                [
                    "/usr/bin/env",
                    "docker-compose",
                    "-f",
                    self.compose_filename,
                    "down",
                    "--remove-orphans",
                ],
                self.dir,
            )
            != 0
        ):
            raise Exception("Could not stop the docker-compose container.")

    def clone(self) -> bool:
        """
        Clone a repository.

        Returns whether an update was done.
        """
        if (
            run_command(
                ["/usr/bin/env", "git", "clone", "-b", self.branch, self.url, self.dir],
                self.workdir,
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
    def kill_orphan_containers(self, repo_id: str):
        """
        Kill all Docker containers for an app.

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

    def replace_config_vars(self, app: App):
        with (app.dir / app.compose_filename).open("r+b") as cfile:
            contents = cfile.read()

            replacements = {
                "DATA_DIR": str(app.workdir / DATA_DIR_NAME / app.id),
                "CACHE_DIR": str(app.workdir / CACHES_DIR_NAME / app.id),
                "REPO_DIR": str(app.workdir / REPOS_DIR_NAME / app.id),
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
            updated_repo = app.clone_or_pull()
            if updated_repo:
                click.echo(f"{app.id}: Repo was updated.")

            # The app needs to be restarted, or is not enabled, so stop it.
            if updated_repo or force_restart or not app.enabled:
                click.echo(f"{app.id}: Stopping...")
                app.stop()
                stopped: Optional[bool] = True
            else:
                stopped = None

            # The app is not running and it should be, so start it.
            if app.enabled and (stopped or not app.is_running()):
                rm.replace_config_vars(app)
                app.start()
                click.echo(f"{app.id}: Starting...")
            else:
                click.echo(f"{app.id}: App does not need to be started.")

        except Exception as e:
            click.echo(f"{app.id}: Error while processing: {e}")
        click.echo("")


def archive_stale_data(repos: List[App], workdir: Path):
    app_names = set(repo.id for repo in repos)

    current_repos = set(
        x.name for x in (workdir / REPOS_DIR_NAME).iterdir() if x.is_dir()
    )
    current_data = set(
        x.name for x in (workdir / DATA_DIR_NAME).iterdir() if x.is_dir()
    )
    current_caches = set(
        x.name for x in (workdir / CACHES_DIR_NAME).iterdir() if x.is_dir()
    )

    rm = AppManager()
    for stale_repo in current_repos - app_names:
        path = workdir / REPOS_DIR_NAME / stale_repo
        click.echo(
            f"The repo for {stale_repo} is stale, stopping any running containers..."
        )
        rm.kill_orphan_containers(stale_repo)
        click.echo(f"Removing {path}...")
        shutil.rmtree(path)

    for stale_data in current_data - app_names:
        path = workdir / DATA_DIR_NAME / stale_data
        click.echo(f"The data for {stale_data} is stale, archiving {path}...")
        path.rename(
            workdir
            / ARCHIVES_DIR_NAME
            / f"{stale_data}-{strftime('%Y-%m-%d_%H-%M-%S')}"
        )

    for stale_caches in current_caches - app_names:
        path = workdir / CACHES_DIR_NAME / stale_caches
        click.echo(f"The cache for {stale_caches} is stale, deleting {path}...")
        shutil.rmtree(path)


@click.command()
@click.option(
    "-c",
    "--config",
    default="harbormaster.yml",
    type=click.Path(exists=True, dir_okay=False, readable=True, resolve_path=True),
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
def cli(config: str, working_dir: str, force_restart: bool, debug: bool):
    global DEBUG
    DEBUG = debug

    workdir = Path(working_dir)
    for directory in (
        ARCHIVES_DIR_NAME,
        CACHES_DIR_NAME,
        DATA_DIR_NAME,
        REPOS_DIR_NAME,
    ):
        # Create the necessary directories.
        (workdir / directory).mkdir(exist_ok=True)

    configuration = yaml.load(open(config), Loader=Loader)
    apps = [
        App(
            id=repo_id,
            configuration=repo_config,
            config_filename=Path(config),
            workdir=workdir,
        )
        for repo_id, repo_config in configuration["apps"].items()
    ]
    archive_stale_data(apps, workdir)
    process_config(apps, force_restart=force_restart)


if __name__ == "__main__":
    cli()
