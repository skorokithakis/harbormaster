#!/usr/bin/env python3
import os
import re
import shutil
import subprocess
import sys
import time
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

MAX_GIT_NETWORK_ATTEMPTS = 3
RETRY_WAIT_SECONDS = 10


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
        cfn = configuration.get("compose_config", ["docker-compose.yml"])
        if isinstance(cfn, str):
            # If the filename is a string, we should turn it into a list.
            cfn = [cfn]
        self.compose_config: List[str] = cfn
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
    def compose_config_command(self) -> List[str]:
        """
        Return a tuple with the command for the filenames of all the Compose files.

        The Compose command line accepts any number of YAML config files,
        and this is a convenience method to return them in a format that's easy to
        use with `subprocess.run`.
        """
        commands = []
        for name in self.compose_config:
            commands.append("-f")
            commands.append(name)

        return commands

    @property
    def dir(self):
        return self.workdir / REPOS_DIR_NAME / self.id

    def _render_config_vars(self):
        """
        Render Harbormaster variables in the Compose file.

        This replaces variables like {{ HM_DATA_DIR }} with their value counterparts.
        """
        for cfn in self.compose_config:
            with (self.dir / cfn).open("r+b") as cfile:
                contents = cfile.read()

                replacements = {
                    "DATA_DIR": str(self.workdir / DATA_DIR_NAME / self.id),
                    "CACHE_DIR": str(self.workdir / CACHES_DIR_NAME / self.id),
                    "REPO_DIR": str(self.workdir / REPOS_DIR_NAME / self.id),
                }
                replacements.update(self.replacements)
                for varname, replacement in replacements.items():
                    contents = re.sub(
                        (r"{{\s*HM_%s\s*}}" % varname).encode(),
                        replacement.encode(),
                        contents,
                    )

                cfile.truncate(0)
                cfile.seek(0)
                cfile.write(contents)

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
                *self.compose_config_command,
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
                *self.compose_config_command,
                "pull",
            ],
            self.dir,
            environment=self.environment,
        )

        if status != 0:
            raise Exception(
                f"Could not pull the docker-compose image:\n{stderr.decode()}"
            )

        status, stdout, stderr = run_command_full(
            [
                "/usr/bin/env",
                "docker-compose",
                *self.compose_config_command,
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
                    *self.compose_config_command,
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

        Return a boolean indicating whether an update was done.
        """
        # Note the old revision for change detection.
        old_rev = self.get_current_hash()
        self.pull_upstream()
        new_rev = self.get_current_hash()

        debug(f"Old rev is {old_rev}, new rev is {new_rev}.")
        if old_rev == new_rev:
            debug("No update required.")
            # No update necessary.
            return False

        return True

    def get_current_hash(self) -> str:
        """Return the git repository's current commit SHA."""
        return (
            run_command_full(["/usr/bin/env", "git", "rev-parse", "HEAD"], self.dir)[1]
            .decode()
            .strip()
        )

    def pull_upstream(self) -> None:
        """
        Pull the upstream changes, making sure they're applied locally.

        This method will do whatever is necessary to make sure that the upstream changes
        are applied locally. Basically, the idea is that, at the end of this method, the
        local repository looks exactly like the remote and branch that was specified, no
        matter what.
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

        if (
            run_command(
                ["/usr/bin/env", "git", "reset", "--hard", f"origin/{self.branch}"],
                self.dir,
            )
            != 0
        ):
            raise Exception("Could not reset local repository to the origin.")

    def clone_or_pull(self) -> bool:
        """Pull a repository, or clone it if it hasn't been initialized yet."""
        for i in range(MAX_GIT_NETWORK_ATTEMPTS):
            try:
                if self.is_repo():
                    click.echo(f"Pulling {self.url} to {self.dir}...")
                    updated = self.pull()
                else:
                    click.echo(f"Cloning {self.url} to {self.dir}...")
                    updated = self.clone()

                self._render_config_vars()
                return updated
            except Exception as e:
                last_exception = e
                if i < MAX_GIT_NETWORK_ATTEMPTS - 1:
                    click.echo(f"Error with git clone/pull request: {e}")
                    click.echo(f"Will retry after {RETRY_WAIT_SECONDS} seconds.")
                    time.sleep(RETRY_WAIT_SECONDS)
        else:
            raise last_exception


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


def process_config(apps: List[App], force_restart: bool = False) -> bool:
    """Process a given configuration file."""
    successes = []
    for app in apps:
        debug("-" * 100)
        click.echo(f"Updating {app.id} ({app.branch})...")
        try:
            if app.enabled:
                updated_repo = app.clone_or_pull()
                if updated_repo:
                    click.echo(f"{app.id}: Repo was updated.")
            else:
                debug(f"{app.id} is disabled, will not pull.")
                updated_repo = False

            # The app needs to be restarted, or is not enabled, so stop it.
            if updated_repo or force_restart or not app.enabled:
                click.echo(f"{app.id}: Stopping...")
                app.stop()
                stopped: Optional[bool] = True
            else:
                stopped = None

            # The app is not running and it should be, so start it.
            if app.enabled and (stopped or not app.is_running()):
                app.start()
                click.echo(f"{app.id}: Starting...")
            else:
                click.echo(f"{app.id}: App does not need to be started.")
            successes.append(True)
        except Exception as e:
            click.echo(f"{app.id}: Error while processing: {e}")
            successes.append(False)
        click.echo("")

    return all(successes)


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
    if not configuration or not configuration.get("apps"):
        click.echo("No apps specified, nothing to do.")
        sys.exit(0)

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
    success = process_config(apps, force_restart=force_restart)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    cli()
