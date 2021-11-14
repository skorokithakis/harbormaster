#!/usr/bin/env python3
import ast
import hashlib
import json
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

import attr
import click
import yaml


DEBUG: bool = False

ARCHIVES_DIR_NAME = "archives"
REPOS_DIR_NAME = "repos"
CACHES_DIR_NAME = "caches"
DATA_DIR_NAME = "data"

CACHE_FILE_NAME = ".harbormaster.cache"

MAX_GIT_NETWORK_ATTEMPTS = 3
RETRY_WAIT_SECONDS = 10


def debug(message: Any) -> None:
    """Print a message if DEBUG is True."""
    if DEBUG:
        click.echo(message)


def _hash_dict(d: Dict) -> str:
    """Repeatably hash a dict."""
    return hashlib.sha1(str(sorted(d.items())).encode()).hexdigest()


def _render_template(template: str, replacements: Dict[str, Any]) -> str:
    """Render a template with the values in replacements."""
    # Perform all defined replacements.
    for varname, replacement in replacements.items():
        template = re.sub(
            r"{{\s*HM_%s(?:\:(.*?))?\s*}}" % varname,
            str(replacement),
            template,
        )

    def replacement_fn(match: re.Match) -> str:
        try:
            value = str(ast.literal_eval(match.group(1)))
        except Exception:
            value = "HM_INVALID_DEFAULT_VALUE"
        return value

    # Replace all undefined replacements with their defaults.
    template = re.sub(
        r"{{\s*HM_(?:.*?)\:(.*?)\s*}}",
        replacement_fn,
        template,
    )
    return template


def _read_var_file(
    filename: Optional[str],
    base_dir: Path,
    app_id: str,
) -> Dict[str, str]:
    """
    Read and parse an environment or replacements file.

    The file will be parsed as YAML if the filename ends in .yml or .yaml, otherwise
    it will be parsed as a plain key=value file.

    Abruptly terminates the program with an error message if the file could
    not be read.
    """
    if not filename:
        return {}

    f = (base_dir / Path(filename)).resolve()
    if not f.is_file():
        sys.exit(
            f'Environment or replacements file for app "{app_id}" '
            f"cannot be read, cannot continue:\n{f}"
        )
    output = {}
    contents = f.read_text()

    if f.suffix.lower() in (".yml", ".yaml"):
        # This file is YAML.
        try:
            output = yaml.safe_load(contents)
            assert type(output) == dict
            assert all(type(x) is str for x in output.keys())
            assert all(type(x) is str for x in output.values())
            # Convert everything to a string.
        except Exception:
            raise ValueError(
                f"{filename} is not valid YAML or does not contain "
                "a single YAML collection of strings."
            )
    else:
        for line in contents.split("\n"):
            if not line:
                continue
            if "=" not in line:
                sys.exit(
                    f"Environment or replacements file for app {app_id} contained a "
                    f"line without an equals sign (=), cannot continue:\n{f}"
                )
            key, value = line.split("=", maxsplit=1)
            output[key] = value
    return output


def _kill_orphan_containers(repo_id: str):
    """
    Kill all Docker containers for an app.

    Instead of issuing a `docker-compose down`, this method looks for all
    running containers that start with "{repo_id}_" (that's why it accepts
    a string instead of an App instance).

    That's because the configuration file might be missing, and we might
    not know what the compose file's name is.
    """
    stdout = _run_command_full(
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
            _run_command(["/usr/bin/env", "docker", "stop", container_id], Path("."))
        )

    if any(return_codes):
        raise Exception("Could not stop some containers.")


def _run_command_full(
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


def _run_command(
    command: List[str], chdir: Path, environment: Dict[str, str] = None
) -> int:
    """Run a command and return its exit code."""
    return _run_command_full(command, chdir, environment=environment)[0]


@attr.s(auto_attribs=True)
class Paths:
    """The relevant working paths for this specific configuration run."""

    workdir: Path
    archives_dir: Path
    repos_dir: Path
    caches_dir: Path
    data_dir: Path
    cache_file: Path

    def create_directories(self):
        """Create all the necessary directories."""
        for directory in (
            self.archives_dir,
            self.repos_dir,
            self.caches_dir,
            self.data_dir,
        ):
            directory.mkdir(exist_ok=True)

    @classmethod
    def for_workdir(cls, workdir: Path):
        """Derive the working paths from a base workdir path."""
        data_dir = workdir / DATA_DIR_NAME
        archives_dir = workdir / ARCHIVES_DIR_NAME
        repos_dir = workdir / REPOS_DIR_NAME
        caches_dir = workdir / CACHES_DIR_NAME
        cache_file = workdir / CACHE_FILE_NAME
        return cls(
            workdir=workdir,
            archives_dir=archives_dir,
            repos_dir=repos_dir,
            caches_dir=caches_dir,
            data_dir=data_dir,
            cache_file=cache_file,
        )


class App:
    def __init__(
        self,
        id: str,
        configuration: Dict[str, Any],
        config_filename: Path,
        paths: Paths,
        cache=Dict[str, str],
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
        self.paths = paths
        self.cache = cache

        self.environment: Dict[str, str] = _read_var_file(
            filename=configuration.get("environment_file"),
            base_dir=config_filename.parent,
            app_id=self.id,
        )
        self.environment.update(
            {
                key: str(value)
                for key, value in configuration.get("environment", {}).items()
            }
        )

        self.replacements: Dict[str, str] = _read_var_file(
            filename=configuration.get("replacements_file", {}),
            base_dir=config_filename.parent,
            app_id=self.id,
        )
        self.replacements.update(
            {
                key: str(value)
                for key, value in configuration.get("replacements", {}).items()
            }
        )

    def check_parameter_changes(self) -> bool:
        """
        Check if the environment/replacements have changed since the last run.

        We do this by hashing the environment/replacements dictionaries and comparing
        those hashes to the hashes in the cache file. If anything goes wrong, we do the
        safe thing and return `True`.

        We also update `self.cache` with the new values, for later writing.
        """
        env_hash = _hash_dict(self.environment)
        replacements_hash = _hash_dict(self.replacements)

        old_env_hash = self.cache.get("environment_hash", "")
        old_replacements_hash = self.cache.get("replacements_hash", "")

        debug(f"Old env hash: {old_env_hash}\nNew env hash: {env_hash}")
        debug(
            f"Old replacements hash: {old_replacements_hash}"
            f"\nNew replacements hash: {replacements_hash}"
        )

        self.cache["environment_hash"] = env_hash
        self.cache["replacements_hash"] = replacements_hash

        return env_hash != old_env_hash or replacements_hash != old_replacements_hash

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
        """Return the app repo directory path."""
        return self.paths.repos_dir / self.id

    @property
    def repo_dir_exists(self) -> bool:
        """Return whether a repository directory exists for this app."""
        return self.dir.exists()

    def _render_config_vars(self):
        """
        Render Harbormaster variables in the Compose file.

        This replaces variables like {{ HM_DATA_DIR }} with their value counterparts.
        """
        for cfn in self.compose_config:
            with (self.dir / cfn).open("r+") as cfile:
                contents = cfile.read()

                replacements = {
                    "DATA_DIR": str(self.paths.data_dir / self.id),
                    "CACHE_DIR": str(self.paths.caches_dir / self.id),
                    "REPO_DIR": str(self.paths.repos_dir / self.id),
                }
                replacements.update(self.replacements)
                contents = _render_template(contents, replacements)

                cfile.truncate(0)
                cfile.seek(0)
                cfile.write(contents)

    def is_repo(self) -> bool:
        """Check whether a repository exists and is actually a repository."""
        if not self.dir.exists():
            return False

        return (
            _run_command(
                ["/usr/bin/env", "git", "rev-parse", "--show-toplevel"], self.dir
            )
            == 0
        )

    def is_running(self) -> bool:
        """Check if the app is running."""
        stdout = _run_command_full(
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
        status, stdout, stderr = _run_command_full(
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

        status, stdout, stderr = _run_command_full(
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
            _run_command(
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
            _run_command(
                ["/usr/bin/env", "git", "clone", "-b", self.branch, self.url, self.dir],
                self.paths.workdir,
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
        if not self.enabled:
            debug("App isn't enabled, will not pull.")
            return False

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
            _run_command_full(["/usr/bin/env", "git", "rev-parse", "HEAD"], self.dir)[1]
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
            _run_command(
                ["/usr/bin/env", "git", "remote", "set-url", "origin", self.url],
                self.dir,
            )
            != 0
        ):
            raise Exception("Could not set origin.")

        if (
            _run_command(
                ["/usr/bin/env", "git", "fetch", "--force", "origin", self.branch],
                self.dir,
            )
            != 0
        ):
            raise Exception("Could not fetch from origin.")

        if (
            _run_command(
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


@attr.s(auto_attribs=True)
class Configuration:
    paths: Paths
    prune: bool = False
    apps: List[App] = []

    @classmethod
    def from_yaml(cls, config: str, paths: Paths) -> "Configuration":
        # Read the cache from the cache file.
        cache = {}
        try:
            if paths.cache_file.exists():
                cache = json.loads(paths.cache_file.read_text())
        except Exception as e:
            click.echo(f"Error while reading cache: {e}")

        configuration = yaml.safe_load(open(config))
        cfg = configuration.get("config", {})
        instance = cls(
            prune=cfg.get("prune", False),
            paths=paths,
            apps=[
                App(
                    id=repo_id,
                    configuration=repo_config,
                    config_filename=Path(config),
                    paths=paths,
                    cache=cache.get(repo_id, {}),
                )
                for repo_id, repo_config in configuration["apps"].items()
            ],
        )
        return instance


def process_config(configuration: Configuration, force_restart: bool = False) -> bool:
    """Process a given configuration file."""
    successes = []
    cache = {"version": 1}
    for app in configuration.apps:
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

            parameters_changed = app.check_parameter_changes()

            # The app needs to be restarted, or is not enabled, so stop it.
            if app.repo_dir_exists and (
                updated_repo or parameters_changed or force_restart or not app.enabled
            ):
                click.echo(f"{app.id}: Stopping...")
                app.stop()
                stopped = True
            else:
                stopped = False

            # The app is not running and it should be, so start it.
            if app.enabled and (stopped or not app.is_running()):
                app.start()
                click.echo(f"{app.id}: Starting...")
            else:
                click.echo(f"{app.id}: App does not need to be started.")

            cache[app.id] = app.cache

            successes.append(True)
        except Exception as e:
            raise
            click.echo(f"{app.id}: Error while processing: {e}")
            successes.append(False)
        click.echo("")

    # Write the cache.
    cache_file = configuration.paths.cache_file
    cache_file.write_text(json.dumps(cache))

    return all(successes)


def archive_stale_data(repos: List[App], paths: Paths):
    app_names = set(repo.id for repo in repos)

    current_repos = set(x.name for x in paths.repos_dir.iterdir() if x.is_dir())
    current_data = set(x.name for x in paths.data_dir.iterdir() if x.is_dir())
    current_caches = set(x.name for x in paths.caches_dir.iterdir() if x.is_dir())

    for stale_repo in current_repos - app_names:
        path = paths.repos_dir / stale_repo
        click.echo(
            f"The repo for {stale_repo} is stale, stopping any running containers..."
        )
        _kill_orphan_containers(stale_repo)
        click.echo(f"Removing {path}...")
        shutil.rmtree(path)

    for stale_data in current_data - app_names:
        path = paths.data_dir / stale_data
        click.echo(f"The data for {stale_data} is stale, archiving {path}...")
        path.rename(
            paths.workdir
            / ARCHIVES_DIR_NAME
            / f"{stale_data}-{strftime('%Y-%m-%d_%H-%M-%S')}"
        )

    for stale_caches in current_caches - app_names:
        path = paths.caches_dir / stale_caches
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
    paths = Paths.for_workdir(workdir)
    paths.create_directories()

    configuration = Configuration.from_yaml(config, paths)
    if not configuration.apps:
        click.echo("No apps specified, nothing to do.")
        sys.exit(0)

    archive_stale_data(configuration.apps, paths)
    success = process_config(configuration, force_restart=force_restart)

    if configuration.prune:
        click.echo("Pruning all unused images...")
        _run_command(
            [
                "/usr/bin/env",
                "docker",
                "system",
                "prune",
                "--all",
                "--force",
            ],
            workdir,
        )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    cli()
