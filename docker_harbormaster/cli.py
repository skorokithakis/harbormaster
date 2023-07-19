#!/usr/bin/env python3
import ast
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from time import strftime
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union

import attr
import click
import yaml
from click_help_colors import HelpColorsGroup

from .utils import AppPaths
from .utils import DATA_DIR_NAME
from .utils import options_to_dict
from .utils import Paths


DEBUG: bool = False

MAX_GIT_NETWORK_ATTEMPTS = 3
RETRY_WAIT_SECONDS = 10


def debug(message: str, force: bool = False) -> None:
    """Print a message if DEBUG is True."""
    if DEBUG or force:
        # If there already is a newline, strip it.
        if message.endswith("\n"):
            message = message[:-1]
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

    Instead of issuing a `docker compose down`, this method looks for all
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
    command: List[Union[str, Path]],
    chdir: Path,
    environment: Dict[str, str] = None,
    print_output: bool = False,
) -> Tuple[int, bytes]:
    """Run a command and return its exit code, stdout, and stderr."""
    # Include the environment in our command.
    env = os.environ.copy()
    if environment:
        env.update(environment)

    wd = os.getcwd()
    os.chdir(chdir)
    debug("Command: " + " ".join([str(x) for x in command]))
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, shell=False
    )

    stdout_list: List[bytes] = []
    if process.stdout:
        try:
            for line in process.stdout:
                stdout_list.append(line)
                debug(line.decode(), force=print_output)
        except KeyboardInterrupt as e:
            os.kill(process.pid, signal.SIGINT)
            process.wait()
            raise e

    returncode = process.wait()
    stdout = b"".join(stdout_list)
    debug(f"Return code: {returncode}")
    os.chdir(wd)
    return (returncode, stdout)


def _run_command(
    command: List[Union[Path, str]], chdir: Path, environment: Dict[str, str] = None
) -> int:
    """Run a command and return its exit code."""
    return _run_command_full(command, chdir, environment=environment)[0]


def _postproc_command_assuming_exitcode0(status, stdout, errmsg: str) -> int:
    """run_command postprocess to throw an exception of 'errmsg' and 'outout' if status != 0"""
    if status != 0:
        raise Exception(f"{errmsg}:\n{stdout.decode()}")

    return status


def _run_command_assuming_exitcode_0(
    command: List[Union[Path, str]],
    chdir: Path,
    errmsg: str,
    environment: Dict[str, str] = None,
) -> int:
    status, stdout = _run_command_full(command, chdir, environment=environment)
    return _postproc_command_assuming_exitcode0(status, stdout, errmsg)


class App:
    def __init__(
        self,
        id: str,
        configuration: Dict[str, Any],
        paths: AppPaths,
        cache=Dict[str, str],
    ):
        """
        Instantiate an app.

        id - The app's ID, used to name its directories.
        configuration - The app's stanza from the configuration file.
        paths - A Paths instance containing all the relevant app-independent paths.
        cache - The app's cache.
        """
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
            base_dir=paths.config_dir,
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
            base_dir=paths.config_dir,
            app_id=self.id,
        )
        self.replacements.update(
            {
                key: str(value)
                for key, value in configuration.get("replacements", {}).items()
            }
        )

        self.configuration_hash = hashlib.sha1(
            yaml.dump(configuration).encode("utf-8")
        ).hexdigest()

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
        configuration_hash = self.configuration_hash

        old_env_hash = self.cache.get("environment_hash", "")
        old_replacements_hash = self.cache.get("replacements_hash", "")
        old_configuration_hash = self.cache.get("configuration_hash", "")

        debug(f"Old env hash: {old_env_hash}\nNew env hash: {env_hash}")
        debug(
            f"Old replacements hash: {old_replacements_hash}"
            f"\nNew replacements hash: {replacements_hash}"
        )
        debug(
            f"Old config hash: {old_configuration_hash}\nNew config hash: {configuration_hash}"
        )

        self.cache["environment_hash"] = env_hash
        self.cache["replacements_hash"] = replacements_hash
        self.cache["configuration_hash"] = configuration_hash

        return (
            env_hash != old_env_hash
            or replacements_hash != old_replacements_hash
            or configuration_hash != old_configuration_hash
        )

    def ev_run_command_full(
        self,
        command: List[Union[str, Path]],
        chdir: Path,
        print_output: bool = False,
    ) -> Tuple[int, bytes]:
        return _run_command_full(
            command, chdir, environment=self.environment, print_output=print_output
        )

    def ev_run_command_assuming_exitcode_0(
        self, command: List[Union[Path, str]], chdir: Path, errmsg: str
    ) -> int:
        status, stdout = self.ev_run_command_full(command, chdir)
        return _postproc_command_assuming_exitcode0(status, stdout, errmsg)

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
    def repo_dir_exists(self) -> bool:
        """Return whether a repository directory exists for this app."""
        return self.paths.repo_dir.exists()

    def _render_config_vars(self):
        """
        Render Harbormaster variables in the Compose file.

        This replaces variables like {{ HM_DATA_DIR }} with their value counterparts.
        """
        # There's a particularity in how the Docker deployment of Harbormaster (ie
        # running Harbormaster itself in a container) works: Harbormaster inside the
        # container tries to tell Compose to mount the apps' volumes in its working
        # directory, but Compose mounts them on the *host* instead. This is because
        # Compose doesn't know that the caller is in a container, it just sees someone
        # ask it to mount the `data` volume into `/main/data/someapp`.
        # We work around that with a hack here by looking for an environment variable
        # with the path to mount on the host.
        data_env_var = os.environ.get("HARBORMASTER_HOST_DATA")
        data_dir = (
            (Path(data_env_var) / DATA_DIR_NAME / self.id)
            if data_env_var
            else self.paths.data_dir
        )

        for cfn in self.compose_config:
            with (self.paths.repo_dir / cfn).open("r+") as cfile:
                contents = cfile.read()

                replacements = {
                    "DATA_DIR": str(data_dir),
                    "CACHE_DIR": str(self.paths.cache_dir),
                    "REPO_DIR": str(self.paths.repo_dir),
                }
                replacements.update(self.replacements)
                contents = _render_template(contents, replacements)

                cfile.truncate(0)
                cfile.seek(0)
                cfile.write(contents)

    def is_repo(self) -> bool:
        """Check whether a repository exists and is actually a repository."""
        if not self.paths.repo_dir.exists():
            return False

        return (
            _run_command(
                ["/usr/bin/env", "git", "rev-parse", "--show-toplevel"],
                self.paths.repo_dir,
            )
            == 0
        )

    def is_running(self) -> bool:
        """Check if the app is running."""
        stdout = self.ev_run_command_full(
            [
                "/usr/bin/env",
                "docker",
                "compose",
                *self.compose_config_command,
                "ps",
                "--services",
                "--filter",
                "status=running",
            ],
            self.paths.repo_dir,
        )[1].strip()

        if stdout:
            debug(f"{self.id} is running.")
        else:
            debug(f"{self.id} is NOT running.")
        # If `docker ps` returned nothing, nothing is running.
        return bool(stdout)

    def start(self, detach=True):
        """Start the Docker containers for this app."""
        status = self.ev_run_command_assuming_exitcode_0(
            [
                "/usr/bin/env",
                "docker",
                "compose",
                *self.compose_config_command,
                "pull",
            ],
            self.paths.repo_dir,
            "Could not pull the Docker image",
        )

        command = [
            "/usr/bin/env",
            "docker",
            "compose",
            *self.compose_config_command,
            "up",
            "--remove-orphans",
            "--build",
        ]
        if detach:
            command.append("--detach")

        status, stdout = self.ev_run_command_full(
            command,
            self.paths.repo_dir,
            print_output=not detach,
        )
        _postproc_command_assuming_exitcode0(
            status, stdout, "Could not start the Docker container"
        )

    def stop(self):
        if not self.is_running():
            # `docker ps` returned nothing, ie nothing is running.
            return

        self.ev_run_command_assuming_exitcode_0(
            [
                "/usr/bin/env",
                "docker",
                "compose",
                *self.compose_config_command,
                "down",
                "--remove-orphans",
            ],
            self.paths.repo_dir,
            "Could not stop the Docker container.",
        )

    def clone(self) -> bool:
        """
        Clone a repository.

        Returns whether an update was done.
        """
        _run_command_assuming_exitcode_0(
            [
                "/usr/bin/env",
                "git",
                "clone",
                "-b",
                self.branch,
                self.url,
                self.paths.repo_dir,
            ],
            self.paths.workdir,
            "Could not clone repository.",
        )

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
            _run_command_full(
                ["/usr/bin/env", "git", "rev-parse", "HEAD"], self.paths.repo_dir
            )[1]
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
        _run_command_assuming_exitcode_0(
            ["/usr/bin/env", "git", "remote", "set-url", "origin", self.url],
            self.paths.repo_dir,
            "Could not set origin.",
        )

        _run_command_assuming_exitcode_0(
            ["/usr/bin/env", "git", "fetch", "--force", "origin", self.branch],
            self.paths.repo_dir,
            "Could not fetch from origin.",
        )

        _run_command_assuming_exitcode_0(
            ["/usr/bin/env", "git", "reset", "--hard", f"origin/{self.branch}"],
            self.paths.repo_dir,
            "Could not reset local repository to the origin.",
        )

    def clone_or_pull(self) -> bool:
        """Pull a repository, or clone it if it hasn't been initialized yet."""
        for _ in range(MAX_GIT_NETWORK_ATTEMPTS):
            try:
                if self.is_repo():
                    click.echo(f"Pulling {self.url} to {self.paths.repo_dir}...")
                    updated = self.pull()
                else:
                    click.echo(f"Cloning {self.url} to {self.paths.repo_dir}...")
                    updated = self.clone()

                self._render_config_vars()
                return updated
            except Exception as e:
                last_exception = e

            click.echo(f"Error with git clone/pull request: {last_exception}")
            click.echo(f"Will retry after {RETRY_WAIT_SECONDS} seconds.")
            time.sleep(RETRY_WAIT_SECONDS)
        raise last_exception


@attr.s(auto_attribs=True)
class Configuration:
    paths: Paths
    prune: bool = False
    apps: List[App] = []

    @classmethod
    def from_yaml(cls, config: Path, paths: Paths) -> "Configuration":
        # Read the cache from the cache file.
        cache = {}
        try:
            if paths.cache_file.exists():
                cache = json.loads(paths.cache_file.read_text())
        except Exception as e:
            click.echo(f"Error while reading cache: {e}")

        configuration = yaml.safe_load(open(config)) or {}
        cfg = configuration.get("config", {})
        instance = cls(
            prune=cfg.get("prune", False),
            paths=paths,
            apps=[
                App(
                    id=app_id,
                    configuration=app_config,
                    paths=AppPaths.from_paths(paths, app_id),
                    cache=cache.get(app_id, {}),
                )
                for app_id, app_config in configuration.get("apps", {}).items()
            ],
        )
        return instance


def process_config(configuration: Configuration, force_restart: bool = False) -> bool:
    """
    Process a given configuration file.

    This is the main function that loads the configuration the file and starts/stops
    apps as needed.
    """
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
            paths.archives_dir / f"{stale_data}-{strftime('%Y-%m-%d_%H-%M-%S')}"
        )

    for stale_caches in current_caches - app_names:
        path = paths.caches_dir / stale_caches
        click.echo(f"The cache for {stale_caches} is stale, deleting {path}...")
        shutil.rmtree(path)


@click.group(cls=HelpColorsGroup, help_headers_color="blue", help_options_color="green")
@click.option("--debug", is_flag=True, help="Print debug information.")
@click.version_option()
def cli(debug: bool):
    global DEBUG
    DEBUG = debug


@cli.command()
@click.option(
    "-c",
    "--config",
    default="harbormaster.yml",
    type=click.Path(
        exists=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        path_type=Path,
    ),
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
        path_type=Path,
    ),
    help="The root directory to work in.",
)
@click.option(
    "-f",
    "--force-restart",
    is_flag=True,
    help="Restart all apps even if their repositories have not changed.",
)
def run(config: Path, working_dir: Path, force_restart: bool):
    workdir = working_dir
    paths = Paths.for_workdir(workdir, config_dir=config.absolute().parent)
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


@cli.command()
@click.option(
    "-d",
    "--working-dir",
    default=tempfile.mkdtemp(prefix="hm_"),
    type=click.Path(
        exists=True,
        file_okay=False,
        readable=True,
        writable=True,
        resolve_path=True,
        path_type=Path,
    ),
    help=(
        "The root directory to work in (if not specified, a temporary directory will "
        "be created."
    ),
)
@click.option(
    "-e",
    "--environment",
    multiple=True,
    help="An environment variable (can be used multiple times).",
)
@click.option(
    "-v",
    "--environment-file",
    type=click.Path(
        exists=True,
        file_okay=True,
        readable=True,
        resolve_path=True,
        path_type=Path,
    ),
    help="The environment file to use.",
)
@click.option(
    "-r",
    "--replacement",
    multiple=True,
    help="A replacement variable (can be used multiple times).",
)
@click.option(
    "-p",
    "--replacements-file",
    type=click.Path(
        exists=True,
        file_okay=True,
        readable=True,
        resolve_path=True,
        path_type=Path,
    ),
    help="The replacements file to use.",
)
@click.option(
    "-c",
    "--compose-file",
    type=click.Path(
        exists=True,
        file_okay=True,
        readable=True,
        resolve_path=True,
        path_type=Path,
    ),
    multiple=True,
    help="The Compose file to use (can be used multiple times).",
)
def test(
    working_dir: Path,
    environment: Tuple[str],
    environment_file: Path,
    replacement: Tuple[str],
    replacements_file: Path,
    compose_file: Tuple[Path],
):
    click.echo(f"Starting app in test mode in {working_dir}...")
    app_id = "test_app"
    # We don't have a config dir for this, so just set the root.
    paths = Paths.for_workdir(working_dir, config_dir=Path("/"))
    paths.create_directories()
    app_paths = AppPaths.from_paths(paths, app_id)
    app_paths.repo_dir = Path(".").absolute()

    repo_config = {
        "enabled": True,
        "url": "https://your.git/repo/url/here",
        "branch": "master",
        "environment_file": environment_file,
        "replacements_file": replacements_file,
    }
    if environment:
        repo_config["environment"] = options_to_dict(environment)
    if replacement:
        repo_config["replacements"] = options_to_dict(replacement)

    if not compose_file:
        compose_file = (Path("docker-compose.yml").absolute(),)

    # Copy the Compose config files to the working directory and render them.
    config_list = []
    for path in compose_file:
        destination = (app_paths.repo_dir / f".{path.name}.hmtemp").absolute()
        shutil.copy(path, destination)
        config_list.append(destination)
    repo_config["compose_config"] = config_list

    app = App(
        id=app_id,
        configuration=repo_config,
        paths=app_paths,
        cache={},
    )
    app._render_config_vars()
    try:
        app.start(detach=False)
    except KeyboardInterrupt:
        click.echo("Interrupted container.")

    # Clean up.
    for file in repo_config["compose_config"]:  # type: ignore
        file.unlink()

    # Beautify the config.
    repo_config.pop("environment_file")
    if environment_file:
        repo_config["environment_file"] = f"some_dir/{environment_file.name}"

    repo_config.pop("replacements_file")
    if replacements_file:
        repo_config["replacements_file"] = f"some_dir/{replacements_file.name}"

    repo_config["compose_config"] = [path.name for path in compose_file]

    # Show it.
    click.secho(
        "\U00002714\U0000FE0F Run finished.\n\n"
        "If everything went well, you can use this stanza in your Harbormaster "
        "config file:\n",
        fg="green",
    )
    click.echo(yaml.dump({"apps": {"myapp": repo_config}}))


if __name__ == "__main__":
    cli()
