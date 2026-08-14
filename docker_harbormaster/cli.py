#!/usr/bin/env python3
import ast
import hashlib
import io
import json
import os
import re
import shlex
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
from typing import Set
from typing import Tuple
from typing import Union

import attr
import click
import yaml
from click_help_colors import HelpColorsGroup
from ruamel.yaml import YAML

from .utils import AppPaths
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


def _parse_compose_file(contents: str) -> Any:
    # Round-trip mode parses YAML 1.2, the version Compose itself uses. PyYAML's
    # YAML 1.1 silently rewrites plain scalars such as `22:22` (sexagesimal 1342),
    # `no`, and `NO` (booleans), changing the meaning of the Compose file. Round-trip
    # mode also preserves comments and quoting, so anything we do not deliberately
    # modify is re-emitted unchanged.
    yaml_handler = YAML()
    return yaml_handler.load(contents)


def _collect_volume_declarations(contents: str) -> Dict[str, Any]:
    """Return the top-level volumes of a Compose file, or an empty dict if it has none."""
    doc = _parse_compose_file(contents)
    if not isinstance(doc, dict):
        return {}
    volumes = doc.get("volumes")
    if not isinstance(volumes, dict):
        return {}
    return volumes


def _configures_volume(config: Any) -> bool:
    """
    Return whether a volume declaration's config makes the volume the user's own.

    A declaration with a driver, driver_opts, external, or name key takes the
    volume over: injecting our own values into Compose's per-key merge would
    conflict with the user's (eg `external: true` alongside our `driver: local`
    rejects the whole project), and a user-supplied name must be kept rather than
    silently overridden by ours. Non-mapping configs count too, as they cannot be
    rewritten safely.
    """
    if config is None:
        # A bare declaration adds nothing to the merged definition.
        return False
    if not isinstance(config, dict):
        return True
    return any(key in config for key in ("driver", "driver_opts", "external", "name"))


def _collect_managed_volume_names(rendered_files: List[str]) -> Set[str]:
    """
    Return the names of the volumes that no Compose file in a stack configures.

    Compose merges the top-level volumes of all the files in a stack per key, so
    whether a volume is bare can only be decided from the union of every file's
    declarations: a volume that is bare in one file but configured in another
    must be left alone, or the merged definition would carry both the user's
    settings and our injected ones.
    """
    declared_configs: Dict[str, List[Any]] = {}
    for contents in rendered_files:
        for name, config in _collect_volume_declarations(contents).items():
            declared_configs.setdefault(name, []).append(config)

    managed_names: Set[str] = set()
    for name, configs in declared_configs.items():
        if not isinstance(name, str):
            # YAML can coerce keys to other types, and we can't make a path from those.
            continue
        if any(_configures_volume(config) for config in configs):
            # At least one file configures the volume, so it is not ours to manage.
            continue
        managed_names.add(name)
    return managed_names


def _inject_managed_volumes(
    contents: str,
    data_dir: Path,
    cache_dir: Path,
    app_id: str,
    managed_names: Optional[Set[str]] = None,
) -> Tuple[str, Dict[str, Path]]:
    """
    Rewrite top-level named volumes in a Compose file into bind-backed local volumes.

    Each rewritten volume is explicitly named `hm_<app_id>_<volume_name>` and
    carries the `com.harbormaster.app` label, so its Docker record can later be
    found and owned without guessing Compose's project name. Volumes that declare a
    driver, driver_opts, external, or name are left untouched, as are volumes with
    any configuration other than a mapping or null. When managed_names is given,
    only those volumes are rewritten, so callers that read a whole Compose stack at
    once can pass the volumes that no file configures. Device directories are
    created here because Docker will not create missing bind device paths on its
    own.

    Returns the rewritten contents and a mapping of each rewritten volume's name to
    its device path, so the volumes can later be reconciled with existing Docker
    volume records.
    """
    doc = _parse_compose_file(contents)
    if not isinstance(doc, dict):
        return contents, {}
    volumes = doc.get("volumes")
    if not isinstance(volumes, dict):
        return contents, {}

    changed = False
    managed_volumes: Dict[str, Path] = {}
    for name, config in volumes.items():
        if not isinstance(name, str):
            # YAML can coerce keys to other types, and we can't make a path from those.
            continue
        if managed_names is not None and name not in managed_names:
            continue
        if config is None:
            config = {}
        elif not isinstance(config, dict):
            # Unknown volume configurations cannot be rewritten safely.
            continue
        if _configures_volume(config):
            continue
        if "/" in name or "\\" in name or name in (".", ".."):
            # Compose accepts such names, but the device path is `base_dir / name`,
            # so a path separator or a `.` path segment would resolve it outside the
            # app's directory (eg `..` points at the shared data/ or caches/ tree).
            # Refuse rather than bind-mount the wrong directory.
            raise ValueError(
                f'Volume name "{name}" in the compose file contains a path '
                'separator or a "." path segment, so it cannot be stored under '
                "the app's data directory. Rename the volume to a plain name."
            )

        base_dir = cache_dir if name.startswith("cache-") else data_dir
        device_dir = base_dir / name
        device_dir.mkdir(parents=True, exist_ok=True)
        # The explicit name and the ownership label must always win over any
        # user-provided values, or the volume would no longer be found and owned
        # by the exact name we reconcile. All other user keys are preserved.
        # A bare `labels:` key parses as YAML null, which must count as absent:
        # `{**None}` would raise TypeError in the mapping branch below.
        existing_labels = config.get("labels", {}) or {}
        if isinstance(existing_labels, list):
            # Compose converts list-form labels to a mapping in which later
            # entries win, so appending keeps the ownership label in control of
            # its key.
            labels: Any = [*existing_labels, f"com.harbormaster.app={app_id}"]
        else:
            labels = {**existing_labels, "com.harbormaster.app": app_id}
        volumes[name] = {
            **config,
            "name": f"hm_{app_id}_{name}",
            "labels": labels,
            "driver": "local",
            "driver_opts": {"type": "none", "o": "bind", "device": str(device_dir)},
        }
        managed_volumes[name] = device_dir
        changed = True

    if not changed:
        return contents, {}
    # ruamel's dump writes to a stream, so capture it in a StringIO to get a string.
    output = io.StringIO()
    yaml_handler = YAML()
    yaml_handler.dump(doc, output)
    return output.getvalue(), managed_volumes


def _read_var_file(
    filename: Optional[Union[str, Path]],
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

    f = (base_dir / filename).resolve()
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
            assert isinstance(output, dict)
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


def _kill_orphan_containers(repo_dir: Path) -> None:
    """
    Kill all Docker containers for an app.

    Instead of issuing a `docker compose down`, this method looks for all
    containers carrying Compose's `com.docker.compose.project.working_dir`
    label pointing at the app's repository directory (that's why it accepts a
    path instead of an App instance). Compose v2 sets that label to the
    absolute path of the directory containing the first `-f` file: that is
    the app's repo directory `repos/<app_id>` in the common case, but a
    subdirectory of it when the app's compose_config points at a nested path.
    The configuration file might also be missing, and we might not know what
    its name is, so a directory path is all we have and all we need.
    Containers are therefore listed together with their label and kept only
    when the label path is the repo directory or lies inside it, compared on
    path components: a raw string-prefix comparison for a stale app `foo`
    would also match the containers of a live app `foo-bar` and remove them,
    along with their writable-layer data. Stopped containers are included
    because they too hold references to the app's volumes.

    Containers created by Compose v1 carry no such label and will not be
    found, nor will any other container without the label: an empty or
    absent label is treated as "not ours", never as a match. That is not a
    regression: the previous v1-style name filter never matched Compose v2
    containers either, and for managed-volume apps the volume-removal
    failure path still prevents us from archiving data out from under a
    container we failed to stop.

    The containers are stopped gracefully and then removed: a hard
    `docker rm -f` would send SIGKILL, and this runs when a user removes
    an app from their config, so an app flushing data on shutdown (a
    database, for example) could lose in-flight writes. Removal, not
    just stopping, is required because a stopped container still holds
    its volume references, so `docker volume rm` would keep failing
    until the container is gone. `docker stop` succeeds on already
    stopped containers too, so the exit-code check below stays valid
    for containers matched by the `-a` flag.
    """
    returncode, stdout = _run_command_full(
        [
            "/usr/bin/env",
            "docker",
            "ps",
            "-a",
            "--format",
            '{{.ID}} {{.Label "com.docker.compose.project.working_dir"}}',
        ],
        Path("."),
    )
    if returncode != 0:
        # A failed listing must not look like "no containers exist", or the
        # app would be archived while its containers are still running and
        # writing into the data directory. Raising lets archive_stale_data
        # apply the uniform warn-and-skip rule for Docker failures.
        raise Exception(
            f"Could not list the Docker containers of the stale app "
            f"{repo_dir.name}: {stdout.decode().strip()}"
        )
    if not stdout:
        # `docker ps` returned nothing, ie no container exists for this app.
        return

    container_ids: List[str] = []
    for line in stdout.decode().split("\n"):
        container_id, _, label = line.partition(" ")
        if not label:
            # The container has no working_dir label, so it is not provably
            # ours and must be ignored.
            continue
        label_dir = Path(label)
        # The label path is kept when it is the repo directory or a
        # subdirectory of it. Comparing path components rather than string
        # prefixes is what keeps `repos/foo` from matching a container
        # labelled `repos/foo-bar`.
        if label_dir.is_relative_to(repo_dir):
            container_ids.append(container_id)

    return_codes = []
    for container_id in container_ids:
        debug(f"Stopping and removing container {container_id}...")
        return_codes.append(
            _run_command(["/usr/bin/env", "docker", "stop", container_id], Path("."))
        )
        return_codes.append(
            _run_command(["/usr/bin/env", "docker", "rm", container_id], Path("."))
        )

    if any(return_codes):
        raise Exception("Could not remove some containers.")


def _run_command_full(
    command: List[Union[str, Path]],
    chdir: Path,
    environment: Optional[Dict[str, str]] = None,
    print_output: bool = False,
) -> Tuple[int, bytes]:
    """Run a command and return its exit code, stdout, and stderr."""
    # Include the environment in our command.
    env = os.environ.copy()
    if environment:
        env.update(environment)

    wd = os.getcwd()
    os.chdir(chdir)
    # We concatenate the command here instead of just passing it to Popen, because the
    # Harbormaster container (the way to deploy HM) uses a symlink inside with the same
    # name as the host directory (to make the paths inside the container match up with
    # the host).
    #
    # We do this because otherwise relative volume paths (e.g. `.:/code`) don't work,
    # as it tries to map the current directory inside the container (e.g. `/main`) to
    # the outside, where it has a different path (e.g. `/home/foo/hm`), so we create
    # a symlink called `/home/foo/hm` inside the container, with `/main` as a target.
    #
    # In order for Compose to see the current directory as the symlink (ie
    # `/home/foo/hm`), instead of the absolute path (ie `/main`), we need to use a shell
    # and cd to the symlink before running Compose.
    #
    # I haven't found another way to do this, but if you do, feel free to change it.
    concatenated_command = f"cd {shlex.quote(str(chdir))}; " + " ".join(
        [shlex.quote(str(c)) for c in command]
    )
    debug(f"Command: {concatenated_command}")
    process = subprocess.Popen(
        concatenated_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        shell=True,
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


def _run_command_capture_output(
    command: List[Union[str, Path]],
    environment: Optional[Dict[str, str]] = None,
) -> Tuple[int, bytes, bytes]:
    """Run a command and return its exit code, stdout, and stderr separately."""
    # Docker writes warnings (config file notices, credential helper messages,
    # DOCKER_HOST deprecations) to stderr while exiting zero, so the streams
    # must be kept apart here: a caller that parses stdout as JSON would choke
    # on the merged output of _run_command_full. Unlike _run_command_full, no
    # shell and cd are needed, as `docker volume` subcommands never resolve
    # relative paths against the working directory.
    # The app's environment is overlaid on the process's, exactly as
    # _run_command_full does: the volume commands must reach the same daemon as
    # `docker compose up`, which runs with the app's environment.
    env = os.environ.copy()
    if environment:
        env.update(environment)
    process = subprocess.run(
        [str(part) for part in command],
        capture_output=True,
        env=env,
    )
    debug(f"Command: {' '.join(str(part) for part in command)}")
    debug(f"Return code: {process.returncode}")
    return process.returncode, process.stdout, process.stderr


def _run_command(
    command: List[Union[Path, str]],
    chdir: Path,
    environment: Optional[Dict[str, str]] = None,
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
    environment: Optional[Dict[str, str]] = None,
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
        self.manage_volumes: bool = configuration.get("manage_volumes", False)
        self.managed_volumes: Dict[str, Path] = {}
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

        # Since Compose now supports env vars in the file, we should insert these there.
        self.environment.update(
            {
                "HM_DATA_DIR": str(self.paths.data_dir),
                "HM_CACHE_DIR": str(self.paths.cache_dir),
                "HM_REPO_DIR": str(self.paths.repo_dir),
            }
        )

        self.replacements: Dict[str, str] = _read_var_file(
            filename=configuration.get("replacements_file", None),
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

    def _render_config_vars(self) -> None:
        """
        Render Harbormaster variables in the Compose files.

        This replaces variables like {{ HM_DATA_DIR }} with their value counterparts.
        If manage_volumes is enabled, top-level named volumes are also rewritten to
        bind mounts backed by the app's data and cache directories, and the rewritten
        volumes are recorded on the app so start() can reconcile them with existing
        Docker volume records.
        """
        if self.manage_volumes:
            # Rebuild the mapping on every render so entries from a previous render
            # don't linger.
            self.managed_volumes = {}

        replacements = {
            "DATA_DIR": str(self.paths.data_dir),
            "CACHE_DIR": str(self.paths.cache_dir),
            "REPO_DIR": str(self.paths.repo_dir),
        }
        replacements.update(self.replacements)

        # Templates must be rendered before the YAML is parsed, so every file is
        # rendered first and the volume rewrite below works on the rendered output.
        rendered_contents: Dict[str, str] = {}
        for cfn in self.compose_config:
            with (self.paths.repo_dir / cfn).open("r") as cfile:
                rendered_contents[cfn] = _render_template(cfile.read(), replacements)

        if self.manage_volumes:
            # Which volumes are managed is decided from every file at once, and
            # each managed volume is then injected into the first file that
            # declares it. Compose merges the files' volume definitions per key,
            # so the injected keys survive the merge and a bare declaration in a
            # later file adds nothing to it.
            managed_names = _collect_managed_volume_names(
                list(rendered_contents.values())
            )
            for cfn, contents in rendered_contents.items():
                contents, injected = _inject_managed_volumes(
                    contents,
                    self.paths.data_dir,
                    self.paths.cache_dir,
                    self.id,
                    managed_names,
                )
                rendered_contents[cfn] = contents
                # Drop the injected volumes from the pending set, so a later file
                # that also declares them bare does not get a second injection.
                managed_names -= set(injected)
                self.managed_volumes.update(injected)

        for cfn, contents in rendered_contents.items():
            with (self.paths.repo_dir / cfn).open("w") as cfile:
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

    def _reconcile_managed_volumes(self) -> None:
        """
        Reconcile Docker volume records with the managed volumes in the compose file.

        Every managed volume is created under the exact name
        `hm_<app_id>_<volume_name>` and carries the `com.harbormaster.app` label, so
        a record is owned by Harbormaster exactly when that label is present; nothing
        about how Compose might have named the volume is guessed. A labelled record
        whose device path no longer matches, eg because the app's repo directory was
        moved or renamed, is only Docker bookkeeping: the actual data lives in the
        device directory, so the record can be removed and `docker compose up` will
        recreate it pointing at the new path. A record without the label holds real
        data elsewhere, and starting the app would collide with it, so we abort
        instead of touching it.
        """
        for volume_name, device_path in self.managed_volumes.items():
            docker_volume_name = f"hm_{self.id}_{volume_name}"
            returncode, stdout, stderr = _run_command_capture_output(
                ["/usr/bin/env", "docker", "volume", "inspect", docker_volume_name],
                environment=self.environment,
            )
            if returncode != 0:
                if "no such volume" not in stderr.decode().lower():
                    # Any failure other than a genuine absence is an operational
                    # error (unreachable daemon, permission error, ...).
                    # Silently continuing could let Compose reuse a colliding
                    # volume we never checked, so the failure must surface.
                    raise Exception(
                        f'Could not inspect the Docker volume "{docker_volume_name}" '
                        f"for app {self.id}: {stderr.decode().strip()}"
                    )
                # No Docker record for this volume, so there is nothing to reconcile.
                continue
            record = json.loads(stdout)[0]
            labels = record.get("Labels") or {}
            if labels.get("com.harbormaster.app") != self.id:
                raise Exception(
                    f'A Docker volume named "{docker_volume_name}" already exists and '
                    f"is not a Harbormaster-managed volume. The app's compose "
                    f'file declares a volume named "{volume_name}" that Harbormaster '
                    "manages, and that name collides with the existing volume. "
                    "Harbormaster stopped before starting this app, so the existing "
                    "volume's data is protected. To fix this, either rename the "
                    "volume in the compose file, or, if the old volume's data is no "
                    f"longer needed or has already been migrated to the app's data "
                    f"directory, remove it with: docker volume rm {docker_volume_name}"
                )
            options = record.get("Options") or {}
            if options.get("device") == str(device_path):
                # The record already points at the managed device path.
                continue
            # Removing the record deletes only Docker bookkeeping, never file
            # data: the data itself lives in the device directory. A failed
            # removal here must fail this app, not the whole run: process_config
            # catches per-app exceptions and reports them, and the app cannot
            # be started while its stale volume record is still in place. The
            # failure is almost always a container still referencing the
            # volume, so the message tells the user exactly how to release it.
            returncode, rm_output = _run_command_full(
                ["/usr/bin/env", "docker", "volume", "rm", docker_volume_name],
                self.paths.repo_dir,
                environment=self.environment,
            )
            if returncode != 0:
                raise Exception(
                    f"Could not remove the stale Docker volume record "
                    f"{docker_volume_name} for app {self.id}: "
                    f"{rm_output.decode().strip()}. The volume is probably "
                    f"still in use by one of the app's containers. Run "
                    f"`docker compose down` in {self.paths.repo_dir} to "
                    f"remove the app's containers and release the volume, "
                    f"then run Harbormaster again."
                )

    def start(self, detach=True):
        """Start the Docker containers for this app."""
        if self.manage_volumes:
            self._reconcile_managed_volumes()

        status = self.ev_run_command_assuming_exitcode_0(
            [
                "/usr/bin/env",
                "docker",
                "compose",
                *self.compose_config_command,
                "pull",
                "--ignore-buildable",
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


def _remove_stale_volume_records(app_name: str, paths: Paths) -> bool:
    """
    Remove the Docker volume records an app removed from the config left behind.

    Only records carrying the app's own `com.harbormaster.app` label, an exact
    match on the app id, are even considered, and of those only records whose
    device path lies inside the workdir's data or caches trees are removed. Such a
    record is pure Docker bookkeeping: the actual data lives in the device
    directory, which the caller has archived, so the record would otherwise linger
    pointing at a path that no longer exists. Any other record holds data
    elsewhere, so it is left completely alone.

    Returns True when every Docker operation for this app succeeded, and False
    when any of them failed, so the caller can leave the app's directories in
    place and the next run genuinely retries the cleanup.
    """
    success = True
    returncode, stdout, stderr = _run_command_capture_output(
        [
            "/usr/bin/env",
            "docker",
            "volume",
            "ls",
            "--filter",
            f"label=com.harbormaster.app={app_name}",
            "--format",
            "{{.Name}}",
        ]
    )
    if returncode != 0:
        # A failed listing is deliberately tolerated here, as a narrow exception
        # to the project's no-forgiving-code rule: any Docker failure while
        # cleaning up a stale app warns and skips that app's filesystem
        # cleanup, to be retried on the next successful run, instead of
        # aborting the whole run. Leaving the app's directories in place is
        # what makes the promised retry real.
        click.echo(
            f"Warning: could not list the Docker volumes of the stale app "
            f"{app_name}: {stderr.decode().strip()}. Its directories will be "
            "left in place and the cleanup retried on the next run."
        )
        return False
    if not stdout:
        # No volumes carry this app's label, so there is nothing to remove.
        return True
    for volume_name in stdout.decode().strip().split("\n"):
        if not volume_name:
            continue
        returncode, inspect_output, inspect_stderr = _run_command_capture_output(
            ["/usr/bin/env", "docker", "volume", "inspect", volume_name]
        )
        if returncode != 0:
            if "no such volume" not in inspect_stderr.decode().lower():
                # An operational failure (unreachable daemon, permission
                # error, ...) must skip this app's cleanup: proceeding would
                # remove the records while pretending the volumes are gone.
                click.echo(
                    f"Warning: could not inspect the Docker volume {volume_name} "
                    f"of the stale app {app_name}: "
                    f"{inspect_stderr.decode().strip()}. Its directories will "
                    "be left in place and the cleanup retried on the next run."
                )
                return False
            # The volume disappeared between listing and inspecting, so there is
            # nothing to remove.
            continue
        record = json.loads(inspect_output)[0]
        device_path = Path((record.get("Options") or {}).get("device", ""))
        # A device path always sits under one of these two directories.
        if not (
            device_path.is_relative_to(paths.data_dir)
            or device_path.is_relative_to(paths.caches_dir)
        ):
            # The volume points outside the workdir, so its data is not ours to
            # discard, whatever it may be.
            continue
        # A failed removal is deliberately tolerated here, as a narrow
        # exception to the project's no-forgiving-code rule: a leftover volume
        # record is harmless bookkeeping whose data lives in the device
        # directory, while raising would abort the entire run and block every
        # other app. The failure is almost always a container that still holds
        # the volume, and the record is retried on the next run.
        returncode, rm_output = _run_command_full(
            ["/usr/bin/env", "docker", "volume", "rm", volume_name],
            paths.workdir,
        )
        if returncode != 0:
            click.echo(
                f"Warning: could not remove the stale Docker volume record "
                f"{volume_name}: {rm_output.decode().strip()}. The volume is "
                "probably still in use by a container, and its record will be "
                "retried on the next run."
            )
            # The app's other records are still attempted, but its cleanup is
            # incomplete: the caller must leave its directories in place, or
            # the next run would never see the app and the retry promised
            # above would never happen.
            success = False
    return success


def archive_stale_data(repos: List[App], paths: Paths) -> None:
    app_names = set(repo.id for repo in repos)

    current_repos = set(x.name for x in paths.repos_dir.iterdir() if x.is_dir())
    current_data = set(x.name for x in paths.data_dir.iterdir() if x.is_dir())
    current_caches = set(x.name for x in paths.caches_dir.iterdir() if x.is_dir())

    # A stale app whose Docker cleanup failed keeps every one of its
    # directories: deleting or renaming them would drop the app from future
    # scans, so the next run would never retry, and a container that is still
    # running would keep writing into an archived directory. The failure is
    # per-app, so the other stale apps are still cleaned up normally.
    failed_cleanups: Set[str] = set()

    for stale_repo in current_repos - app_names:
        click.echo(
            f"The repo for {stale_repo} is stale, stopping any running containers..."
        )
        try:
            _kill_orphan_containers(paths.repos_dir / stale_repo)
        except Exception as e:
            # The container cleanup is the only Docker work in this loop that
            # raises (a failed `docker ps`, stop or rm), so this narrow
            # try/except is the deliberate warn-and-continue exception to the
            # project's no-forgiving-code rule, not a safety net.
            failed_cleanups.add(stale_repo)
            click.echo(
                f"Warning: could not clean up the Docker containers of the stale "
                f"app {stale_repo}: {e}. Its directories will be left in place "
                "and the cleanup retried on the next run."
            )

    # Volume records are removed here, after the containers of the stale repos
    # were removed (a volume in use cannot be removed) and before the repo and
    # data dirs are archived (the records point at those dirs, so once the
    # dirs are gone the records would be stale bookkeeping). A stale app may
    # appear in only some of the sets, eg only its data dir may survive a
    # previous cleanup, so the union is considered here. The repo dirs must
    # survive until after this cleanup: a failure above must leave the repo
    # dir in place, or the next run would not see the app in the repos dir
    # and would never remove its containers again, leaving its volumes in
    # use forever.
    stale_names = (current_repos | current_data | current_caches) - app_names
    for stale_name in stale_names:
        if not _remove_stale_volume_records(stale_name, paths):
            failed_cleanups.add(stale_name)

    for stale_repo in current_repos - app_names:
        if stale_repo in failed_cleanups:
            continue
        path = paths.repos_dir / stale_repo
        click.echo(f"Removing {path}...")
        shutil.rmtree(path)

    for stale_data in current_data - app_names:
        if stale_data in failed_cleanups:
            continue
        path = paths.data_dir / stale_data
        click.echo(f"The data for {stale_data} is stale, archiving {path}...")
        path.rename(
            paths.archives_dir / f"{stale_data}-{strftime('%Y-%m-%d_%H-%M-%S')}"
        )

    for stale_caches in current_caches - app_names:
        if stale_caches in failed_cleanups:
            continue
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
    click.echo("Finished successfully." if success else "Finished with errors.")
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
        "\U00002714\U0000fe0f Run finished.\n\n"
        "If everything went well, you can use this stanza in your Harbormaster "
        "config file:\n",
        fg="green",
    )
    click.echo(yaml.dump({"apps": {"myapp": repo_config}}))


if __name__ == "__main__":
    cli()
