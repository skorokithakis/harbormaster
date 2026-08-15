import json
import shutil
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union
from unittest.mock import patch

import pytest
import yaml
from ruamel.yaml import YAML

from docker_harbormaster import cli
from docker_harbormaster.utils import AppPaths
from docker_harbormaster.utils import Paths

cli.DEBUG = True


def test_template() -> None:
    replacements = {"FOO": 3, "BAR": 4}
    templates = [
        ("""{{ HM_FOO }}, {{ HM_BAR }}, {{ HM_BAZ:80 }}""", "3, 4, 80"),
        ("""{{ HM_FOO }} {{ HM_BAZ }}""", "3 {{ HM_BAZ }}"),
        ("""{{ HM_FOO }} {{ HM_FOO }} {{ HM_FOO }}""", "3 3 3"),
        ("""{{ HM_FOO }} {{ BAR }}""", "3 {{ BAR }}"),
        ("""{{ HM_BAR }}, {{ HM_BAZ:a } }}""", "4, HM_INVALID_DEFAULT_VALUE"),
        ("""{{ HM_BAR }}, {{ HM_BAZ:"hello" }}""", "4, hello"),
    ]
    for template, result in templates:
        assert cli._render_template(template, replacements) == result


def test_var_reading(tmpdir: Path) -> None:
    tmpdir = Path(tmpdir)

    filename = tmpdir / "env.yaml"

    d = {"FOO": "bar", "BAZ": "3"}
    with open(filename, "w") as outfile:
        outfile.write(yaml.safe_dump(d))
    assert cli._read_var_file(filename, tmpdir, "id") == d

    # Dump the file improperly, with ints as ints instead of strings.
    with open(filename, "w") as outfile:
        outfile.write("\n".join(f"{key}: {value}" for key, value in d.items()))
    with pytest.raises(ValueError):
        cli._read_var_file(filename, tmpdir, "id")

    with open(filename, "w") as outfile:
        outfile.write("- 1\n- 2")
    with pytest.raises(ValueError):
        cli._read_var_file(filename, tmpdir, "id")

    with open(filename, "w") as outfile:
        outfile.write("foo: 1\nbar:\n  - 1\n  - 2")
    with pytest.raises(ValueError):
        cli._read_var_file(filename, tmpdir, "id")

    filename = tmpdir / "env.txt"

    d = {"FOO": "bar", "BAZ": "3"}
    with open(filename, "w") as outfile:
        outfile.write("\n".join(f"{key}={value}" for key, value in d.items()))
    assert cli._read_var_file(filename, tmpdir, "id") == d


def test_inject_managed_volumes(tmpdir: Path) -> None:
    tmpdir = Path(tmpdir)
    data_dir = tmpdir / "data"
    cache_dir = tmpdir / "caches"
    contents = """services:
  web:
    image: app
volumes:
  myvol:
  cache-myvol:
  externalvol:
    external: true
  drivervol:
    driver: local
  optsvol:
    driver_opts:
      type: volume
  labelledvol:
    labels:
      keep: me
  nullvol:
    labels:
"""
    output, managed_volumes = cli._inject_managed_volumes(
        contents, data_dir, cache_dir, "test_app"
    )
    doc = yaml.safe_load(output)
    assert doc["volumes"]["myvol"] == {
        "name": "hm_test_app_myvol",
        "labels": {"com.harbormaster.app": "test_app"},
        "driver": "local",
        "driver_opts": {
            "type": "none",
            "o": "bind",
            "device": str(data_dir / "myvol"),
        },
    }
    assert doc["volumes"]["cache-myvol"]["driver_opts"]["device"] == str(
        cache_dir / "cache-myvol"
    )
    assert doc["volumes"]["cache-myvol"]["name"] == "hm_test_app_cache-myvol"
    assert doc["volumes"]["externalvol"] == {"external": True}
    assert doc["volumes"]["drivervol"] == {"driver": "local"}
    assert doc["volumes"]["optsvol"] == {"driver_opts": {"type": "volume"}}
    # User labels are preserved, and the ownership label is added alongside them.
    assert doc["volumes"]["labelledvol"]["driver"] == "local"
    assert doc["volumes"]["labelledvol"]["labels"] == {
        "keep": "me",
        "com.harbormaster.app": "test_app",
    }
    # An empty `labels:` key parses as YAML null, which counts as absent.
    assert doc["volumes"]["nullvol"]["labels"] == {"com.harbormaster.app": "test_app"}
    # The device directories must exist before `docker compose up` runs.
    assert (data_dir / "myvol").is_dir()
    assert (cache_dir / "cache-myvol").is_dir()
    assert not (data_dir / "externalvol").exists()
    # Only the rewritten volumes are reported as managed.
    assert managed_volumes == {
        "myvol": data_dir / "myvol",
        "cache-myvol": cache_dir / "cache-myvol",
        "labelledvol": data_dir / "labelledvol",
        "nullvol": data_dir / "nullvol",
    }


def test_inject_managed_volumes_list_form_labels(tmpdir: Path) -> None:
    tmpdir = Path(tmpdir)
    contents = """volumes:
  myvol:
    labels:
      - "example=value"
"""
    output, managed_volumes = cli._inject_managed_volumes(
        contents, tmpdir, tmpdir, "test_app"
    )
    doc = yaml.safe_load(output)
    assert doc["volumes"]["myvol"]["driver"] == "local"
    # List-form labels are kept in list form, with the ownership label appended:
    # Compose converts the list to a mapping where later entries win, so ours
    # stays in control of the ownership key.
    assert doc["volumes"]["myvol"]["labels"] == [
        "example=value",
        "com.harbormaster.app=test_app",
    ]
    assert managed_volumes == {"myvol": tmpdir / "myvol"}


def test_inject_managed_volumes_rejects_dangerous_names(tmpdir: Path) -> None:
    tmpdir = Path(tmpdir)
    data_dir = tmpdir / "data"
    # `base_dir / ".."` resolves to the shared data/ tree, so a volume named
    # `..` would bind-mount the wrong directory and is refused.
    with pytest.raises(ValueError):
        cli._inject_managed_volumes("volumes:\n  '..':\n", data_dir, tmpdir, "test_app")
    with pytest.raises(ValueError):
        cli._inject_managed_volumes("volumes:\n  '.':\n", data_dir, tmpdir, "test_app")
    # A path separator would likewise point the device outside the app's directory.
    with pytest.raises(ValueError):
        cli._inject_managed_volumes(
            "volumes:\n  'foo/bar':\n", data_dir, tmpdir, "test_app"
        )
    # Nothing was written to the disk for the rejected volumes.
    assert not data_dir.exists()


def test_inject_managed_volumes_preserves_scalar_semantics(tmpdir: Path) -> None:
    tmpdir = Path(tmpdir)
    contents = """services:
  web:
    image: app
    ports:
      - 22:22
      - 53:53
    restart: no
    environment:
      TZ: NO
volumes:
  myvol:
"""
    # Compose parses YAML 1.2, so the output is read back with ruamel's round-trip
    # mode, which implements YAML 1.2. PyYAML implements YAML 1.1 and would itself
    # corrupt the very scalars under test.
    yaml_handler = YAML()
    original = yaml_handler.load(contents)
    output, managed_volumes = cli._inject_managed_volumes(
        contents, tmpdir, tmpdir, "test_app"
    )
    parsed = yaml_handler.load(output)
    # YAML 1.1 would turn `22:22` into the sexagesimal integer 1342 and `no`/`NO`
    # into booleans, which is exactly the corruption this test guards against.
    assert (
        parsed["services"]["web"]["ports"]
        == original["services"]["web"]["ports"]
        == ["22:22", "53:53"]
    )
    assert (
        parsed["services"]["web"]["restart"]
        == original["services"]["web"]["restart"]
        == "no"
    )
    assert (
        parsed["services"]["web"]["environment"]["TZ"]
        == original["services"]["web"]["environment"]["TZ"]
        == "NO"
    )
    assert parsed["volumes"]["myvol"]["driver_opts"]["device"] == str(tmpdir / "myvol")
    assert managed_volumes == {"myvol": tmpdir / "myvol"}


def test_manage_volumes_off_by_default(tmpdir: Path) -> None:
    tmpdir = Path(tmpdir)
    paths = Paths.for_workdir(tmpdir, config_dir=tmpdir)
    paths.create_directories()
    app_paths = AppPaths.from_paths(paths, "test_app")
    app_paths.repo_dir.mkdir()
    compose_contents = "services:\n  web:\n    image: app\nvolumes:\n  myvol:\n"
    (app_paths.repo_dir / "docker-compose.yml").write_text(compose_contents)

    app = cli.App(
        id="test_app",
        configuration={"url": "https://example.com/repo"},
        paths=app_paths,
        cache={},
    )
    app._render_config_vars()

    assert app.manage_volumes is False
    # Rendered output must be byte-identical when the flag is absent.
    assert (app_paths.repo_dir / "docker-compose.yml").read_text() == compose_contents


def test_manage_volumes_on(tmpdir: Path) -> None:
    tmpdir = Path(tmpdir)
    paths = Paths.for_workdir(tmpdir, config_dir=tmpdir)
    paths.create_directories()
    app_paths = AppPaths.from_paths(paths, "test_app")
    app_paths.repo_dir.mkdir()
    compose_contents = """services:
  web:
    image: app
volumes:
  myvol:
  cache-myvol:
"""
    (app_paths.repo_dir / "docker-compose.yml").write_text(compose_contents)

    app = cli.App(
        id="test_app",
        configuration={"url": "https://example.com/repo", "manage_volumes": True},
        paths=app_paths,
        cache={},
    )
    app._render_config_vars()

    doc = yaml.safe_load((app_paths.repo_dir / "docker-compose.yml").read_text())
    assert doc["volumes"]["myvol"]["driver_opts"]["device"] == str(
        app_paths.data_dir / "myvol"
    )
    assert doc["volumes"]["cache-myvol"]["driver_opts"]["device"] == str(
        app_paths.cache_dir / "cache-myvol"
    )
    # The rewritten volumes must carry the exact name and ownership label that
    # reconciliation later relies on, so nothing is ever guessed.
    assert doc["volumes"]["myvol"]["name"] == "hm_test_app_myvol"
    assert doc["volumes"]["myvol"]["labels"] == {"com.harbormaster.app": "test_app"}
    assert (app_paths.data_dir / "myvol").is_dir()
    assert (app_paths.cache_dir / "cache-myvol").is_dir()
    # The rendered volumes must be recorded for later reconciliation.
    assert app.managed_volumes == {
        "myvol": app_paths.data_dir / "myvol",
        "cache-myvol": app_paths.cache_dir / "cache-myvol",
    }


def test_manage_volumes_override_external_volume_left_alone(tmpdir: Path) -> None:
    tmpdir = Path(tmpdir)
    paths = Paths.for_workdir(tmpdir, config_dir=tmpdir)
    paths.create_directories()
    app_paths = AppPaths.from_paths(paths, "test_app")
    app_paths.repo_dir.mkdir()
    (app_paths.repo_dir / "docker-compose.yml").write_text("volumes:\n  foo:\n")
    (app_paths.repo_dir / "docker-compose.override.yml").write_text(
        "volumes:\n  foo:\n    external: true\n"
    )

    app = cli.App(
        id="test_app",
        configuration={
            "url": "https://example.com/repo",
            "manage_volumes": True,
            "compose_config": [
                "docker-compose.yml",
                "docker-compose.override.yml",
            ],
        },
        paths=app_paths,
        cache={},
    )
    app._render_config_vars()

    base_doc = yaml.safe_load((app_paths.repo_dir / "docker-compose.yml").read_text())
    override_doc = yaml.safe_load(
        (app_paths.repo_dir / "docker-compose.override.yml").read_text()
    )
    # The override configures the volume, so the base's bare declaration is left
    # alone: injecting driver/driver_opts would make Compose reject the merged
    # project with `conflicting parameters "external" and "driver" specified`.
    assert base_doc["volumes"]["foo"] is None
    assert override_doc["volumes"]["foo"] == {"external": True}
    assert not (app_paths.data_dir / "foo").exists()
    # The volume is not recorded as managed, so it is never reconciled.
    assert app.managed_volumes == {}


def test_manage_volumes_override_named_volume_left_alone(tmpdir: Path) -> None:
    tmpdir = Path(tmpdir)
    paths = Paths.for_workdir(tmpdir, config_dir=tmpdir)
    paths.create_directories()
    app_paths = AppPaths.from_paths(paths, "test_app")
    app_paths.repo_dir.mkdir()
    (app_paths.repo_dir / "docker-compose.yml").write_text("volumes:\n  myvol:\n")
    (app_paths.repo_dir / "docker-compose.override.yml").write_text(
        "volumes:\n  myvol:\n    name: user_volume_name\n"
    )

    app = cli.App(
        id="test_app",
        configuration={
            "url": "https://example.com/repo",
            "manage_volumes": True,
            "compose_config": [
                "docker-compose.yml",
                "docker-compose.override.yml",
            ],
        },
        paths=app_paths,
        cache={},
    )
    app._render_config_vars()

    base_doc = yaml.safe_load((app_paths.repo_dir / "docker-compose.yml").read_text())
    override_doc = yaml.safe_load(
        (app_paths.repo_dir / "docker-compose.override.yml").read_text()
    )
    # A user-supplied name is kept as-is, and ours is not silently injected
    # over it.
    assert base_doc["volumes"]["myvol"] is None
    assert override_doc["volumes"]["myvol"] == {"name": "user_volume_name"}
    assert app.managed_volumes == {}


def test_manage_volumes_bare_volume_in_two_files_injected_once(tmpdir: Path) -> None:
    tmpdir = Path(tmpdir)
    paths = Paths.for_workdir(tmpdir, config_dir=tmpdir)
    paths.create_directories()
    app_paths = AppPaths.from_paths(paths, "test_app")
    app_paths.repo_dir.mkdir()
    (app_paths.repo_dir / "docker-compose.yml").write_text("volumes:\n  myvol:\n")
    (app_paths.repo_dir / "docker-compose.override.yml").write_text(
        "volumes:\n  myvol:\n"
    )

    app = cli.App(
        id="test_app",
        configuration={
            "url": "https://example.com/repo",
            "manage_volumes": True,
            "compose_config": [
                "docker-compose.yml",
                "docker-compose.override.yml",
            ],
        },
        paths=app_paths,
        cache={},
    )
    app._render_config_vars()

    base_doc = yaml.safe_load((app_paths.repo_dir / "docker-compose.yml").read_text())
    override_doc = yaml.safe_load(
        (app_paths.repo_dir / "docker-compose.override.yml").read_text()
    )
    # The volume is bare in both files, so it is injected exactly once, into the
    # first file that declares it; the override's bare declaration adds nothing
    # to Compose's per-key merge.
    assert base_doc["volumes"]["myvol"]["name"] == "hm_test_app_myvol"
    assert base_doc["volumes"]["myvol"]["driver"] == "local"
    assert override_doc["volumes"]["myvol"] is None
    assert (app_paths.data_dir / "myvol").is_dir()
    assert app.managed_volumes == {"myvol": app_paths.data_dir / "myvol"}


def _make_compose_test_app(
    tmpdir: Path, configuration: Optional[Dict[str, Any]] = None
) -> cli.App:
    """Return an App whose repo dir exists, for compose-file resolution tests."""
    tmpdir = Path(tmpdir)
    paths = Paths.for_workdir(tmpdir, config_dir=tmpdir)
    paths.create_directories()
    app_paths = AppPaths.from_paths(paths, "test_app")
    app_paths.repo_dir.mkdir()
    app = cli.App(
        id="test_app",
        configuration={"url": "https://example.com/repo", **(configuration or {})},
        paths=app_paths,
        cache={},
    )
    return app


@pytest.mark.parametrize(
    "filename",
    ["compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml"],
)
def test_compose_file_discovery_finds_each_candidate(
    tmpdir: Path, filename: str
) -> None:
    # Every name in the search order is discovered when it is the only
    # candidate present, and the discovered name is used consistently,
    # including on the Compose command line.
    app = _make_compose_test_app(tmpdir)
    (app.paths.repo_dir / filename).write_text("services:\n")
    assert app.compose_config == [filename]
    assert app.compose_config_command == ["-f", filename]


def test_compose_file_discovery_prefers_compose_yaml(tmpdir: Path) -> None:
    # compose.yaml wins over docker-compose.yml, matching Compose v2, even
    # though docker-compose.yml is the legacy default name.
    app = _make_compose_test_app(tmpdir)
    (app.paths.repo_dir / "docker-compose.yml").write_text("services:\n")
    (app.paths.repo_dir / "compose.yaml").write_text("services:\n")
    assert app.compose_config == ["compose.yaml"]


def test_compose_file_resolution_is_cached(tmpdir: Path) -> None:
    # Resolution happens once, after clone/pull, and the result stays stable
    # for the whole run even if the file disappears later.
    app = _make_compose_test_app(tmpdir)
    (app.paths.repo_dir / "compose.yaml").write_text("services:\n")
    assert app.compose_config == ["compose.yaml"]
    (app.paths.repo_dir / "compose.yaml").unlink()
    (app.paths.repo_dir / "docker-compose.yml").write_text("services:\n")
    assert app.compose_config == ["compose.yaml"]


def test_explicit_compose_config_string_used_verbatim(tmpdir: Path) -> None:
    app = _make_compose_test_app(
        tmpdir, configuration={"compose_config": "my-compose.yml"}
    )
    (app.paths.repo_dir / "my-compose.yml").write_text("services:\n")
    assert app.compose_config == ["my-compose.yml"]
    assert app.compose_config_command == ["-f", "my-compose.yml"]


def test_explicit_compose_config_list_used_verbatim(tmpdir: Path) -> None:
    app = _make_compose_test_app(
        tmpdir,
        configuration={
            "compose_config": ["docker-compose.yml", "docker-compose.override.yml"]
        },
    )
    (app.paths.repo_dir / "docker-compose.yml").write_text("services:\n")
    (app.paths.repo_dir / "docker-compose.override.yml").write_text("services:\n")
    assert app.compose_config == [
        "docker-compose.yml",
        "docker-compose.override.yml",
    ]
    assert app.compose_config_command == [
        "-f",
        "docker-compose.yml",
        "-f",
        "docker-compose.override.yml",
    ]


def test_explicit_compose_config_bypasses_discovery(tmpdir: Path) -> None:
    # A discoverable compose.yaml must not win over a name the user set.
    app = _make_compose_test_app(tmpdir, configuration={"compose_config": "custom.yml"})
    (app.paths.repo_dir / "custom.yml").write_text("services:\n")
    (app.paths.repo_dir / "compose.yaml").write_text("services:\n")
    assert app.compose_config == ["custom.yml"]


def test_missing_explicit_compose_file_raises(tmpdir: Path) -> None:
    app = _make_compose_test_app(tmpdir, configuration={"compose_config": "nope.yml"})
    with pytest.raises(Exception) as exc_info:
        _ = app.compose_config
    # The error names the app and the missing path.
    message = str(exc_info.value)
    assert "test_app" in message
    assert "nope.yml" in message


def test_missing_explicit_compose_file_in_list_raises(tmpdir: Path) -> None:
    app = _make_compose_test_app(
        tmpdir,
        configuration={"compose_config": ["docker-compose.yml", "override.yml"]},
    )
    (app.paths.repo_dir / "docker-compose.yml").write_text("services:\n")
    with pytest.raises(Exception) as exc_info:
        _ = app.compose_config
    message = str(exc_info.value)
    assert "test_app" in message
    assert "override.yml" in message


def test_no_compose_file_raises_with_search_list(tmpdir: Path) -> None:
    app = _make_compose_test_app(tmpdir)
    with pytest.raises(Exception) as exc_info:
        _ = app.compose_config
    # The error names the app and every searched filename.
    message = str(exc_info.value)
    assert "test_app" in message
    for name in (
        "compose.yaml",
        "compose.yml",
        "docker-compose.yaml",
        "docker-compose.yml",
    ):
        assert name in message


def test_missing_compose_file_skips_git_retry(tmpdir: Path, capsys: Any) -> None:
    # A missing Compose file is not a network problem: it must not be
    # reported as a git failure, and it must not be retried with sleeps.
    app = _make_compose_test_app(tmpdir)
    with patch.object(cli.App, "is_repo", return_value=True):
        with patch.object(cli.App, "pull", return_value=False):
            with patch("docker_harbormaster.cli.time.sleep") as mock_sleep:
                with pytest.raises(Exception) as exc_info:
                    app.clone_or_pull()
    mock_sleep.assert_not_called()
    output = capsys.readouterr().out
    assert "Error with git clone/pull request" not in output
    message = str(exc_info.value)
    assert "test_app" in message
    assert "compose.yaml" in message


def _make_managed_app(tmpdir: Path) -> cli.App:
    tmpdir = Path(tmpdir)
    paths = Paths.for_workdir(tmpdir, config_dir=tmpdir)
    paths.create_directories()
    app_paths = AppPaths.from_paths(paths, "test_app")
    app_paths.repo_dir.mkdir()
    app = cli.App(
        id="test_app",
        configuration={"url": "https://example.com/repo", "manage_volumes": True},
        paths=app_paths,
        cache={},
    )
    app.managed_volumes = {"myvol": app_paths.data_dir / "myvol"}
    return app


def _mock_docker_commands(
    return_value: Tuple[int, bytes],
) -> Tuple[Any, List[List[Union[str, Path]]]]:
    """Return a mock for _run_command_full that records the issued commands."""
    commands = []

    def fake_run_command_full(
        command: List[Union[str, Path]],
        chdir: Path,
        environment: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> Tuple[int, bytes]:
        commands.append(command)
        return return_value

    return patch(
        "docker_harbormaster.cli._run_command_full", side_effect=fake_run_command_full
    ), commands


def _mock_docker_ps_working_dir_listing(
    containers: Dict[Path, List[str]],
    unlabelled: Optional[List[str]] = None,
) -> Tuple[Any, List[List[Union[str, Path]]]]:
    """Return a mock for _run_command_full that lists containers with their working_dir label."""
    commands = []

    def fake_run_command_full(
        command: List[Union[str, Path]],
        chdir: Path,
        environment: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> Tuple[int, bytes]:
        commands.append(command)
        if command[:3] != ["/usr/bin/env", "docker", "ps"]:
            return (0, b"")
        lines = []
        for label_path, ids in containers.items():
            for container_id in ids:
                lines.append(f"{container_id} {label_path}")
        # A container without the label renders as its ID and an empty label.
        for container_id in unlabelled or []:
            lines.append(f"{container_id} ")
        if not lines:
            # `docker ps` prints nothing when no container exists.
            return (0, b"")
        return (0, ("\n".join(lines) + "\n").encode())

    return patch(
        "docker_harbormaster.cli._run_command_full", side_effect=fake_run_command_full
    ), commands


def _mock_volume_commands(
    capture_return: Tuple[int, bytes, bytes],
) -> Tuple[Any, Any, List[List[Union[str, Path]]]]:
    """Return mocks for the capture helper and _run_command_full that record the issued commands."""
    commands = []

    def fake_capture(
        command: List[Union[str, Path]], **kwargs: Any
    ) -> Tuple[int, bytes, bytes]:
        commands.append(command)
        return capture_return

    def fake_run_command_full(
        command: List[Union[str, Path]],
        chdir: Path,
        environment: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> Tuple[int, bytes]:
        commands.append(command)
        return (0, b"")

    return (
        patch(
            "docker_harbormaster.cli._run_command_capture_output",
            side_effect=fake_capture,
        ),
        patch(
            "docker_harbormaster.cli._run_command_full",
            side_effect=fake_run_command_full,
        ),
        commands,
    )


def _inspected_volumes(
    commands: List[List[Union[str, Path]]],
) -> List[str]:
    """Return the volume names that were inspected by the issued commands."""
    return [
        str(command[4])
        for command in commands
        if command[:4] == ["/usr/bin/env", "docker", "volume", "inspect"]
    ]


def _removed_volumes(commands: List[List[Union[str, Path]]]) -> List[str]:
    """Return the volume names that were removed by the issued commands."""
    return [
        str(command[4])
        for command in commands
        if command[:4] == ["/usr/bin/env", "docker", "volume", "rm"]
    ]


def _volume_ls_label_filters(
    commands: List[List[Union[str, Path]]],
) -> List[str]:
    """Return the label filters of the issued `docker volume ls` commands."""
    return [
        str(command[5])
        for command in commands
        if command[:4] == ["/usr/bin/env", "docker", "volume", "ls"]
    ]


def test_reconcile_managed_volumes_no_record(tmpdir: Path) -> None:
    app = _make_managed_app(tmpdir)
    # Docker reports a missing volume on stderr while exiting nonzero: that is
    # a genuine absence, so nothing is reconciled.
    mock_capture, mock_full, commands = _mock_volume_commands(
        (1, b"", b"Error: No such volume: hm_test_app_myvol")
    )
    with mock_capture, mock_full:
        app._reconcile_managed_volumes()
    assert _inspected_volumes(commands) == ["hm_test_app_myvol"]
    assert _removed_volumes(commands) == []


def test_reconcile_managed_volumes_daemon_unreachable_raises(tmpdir: Path) -> None:
    app = _make_managed_app(tmpdir)
    # An unreachable daemon is not an absent volume: silently proceeding could
    # let Compose reuse a colliding volume we never checked, so the failure
    # must surface as an error instead.
    mock_capture, mock_full, commands = _mock_volume_commands(
        (
            1,
            b"",
            b"Cannot connect to the Docker daemon at "
            b"unix:///var/run/docker.sock. Is the docker daemon running?",
        )
    )
    with mock_capture, mock_full:
        with pytest.raises(Exception) as exc_info:
            app._reconcile_managed_volumes()
    message = str(exc_info.value)
    assert "hm_test_app_myvol" in message
    assert "docker daemon" in message
    assert _removed_volumes(commands) == []


def test_reconcile_managed_volumes_parses_despite_stderr_warning(tmpdir: Path) -> None:
    app = _make_managed_app(tmpdir)
    device_path = app.managed_volumes["myvol"]
    record = json.dumps(
        [
            {
                "Driver": "local",
                "Labels": {"com.harbormaster.app": "test_app"},
                "Options": {"type": "none", "o": "bind", "device": str(device_path)},
            }
        ]
    ).encode()
    # Docker writes warnings (config file notices, credential helper messages)
    # to stderr while exiting zero, so the JSON is parsed from stdout only;
    # and a record that already points at the managed device path is left
    # alone, so nothing is removed.
    mock_capture, mock_full, commands = _mock_volume_commands(
        (
            0,
            record,
            b"WARNING: The DOCKER_HOST environment variable is deprecated\n",
        )
    )
    with mock_capture, mock_full:
        app._reconcile_managed_volumes()
    assert _inspected_volumes(commands) == ["hm_test_app_myvol"]
    assert _removed_volumes(commands) == []


def test_reconcile_managed_volumes_unlabelled_record_refused(tmpdir: Path) -> None:
    app = _make_managed_app(tmpdir)
    # Any record without the ownership label is refused, whatever its shape:
    # one whose device happens to match the managed path (a coincidence, the
    # label is the only proof of ownership), a stale bind record, and a
    # non-bind record.
    records = [
        {
            "Driver": "local",
            "Options": {
                "type": "none",
                "o": "bind",
                "device": str(app.managed_volumes["myvol"]),
            },
        },
        {
            "Driver": "local",
            "Options": {
                "type": "none",
                "o": "bind",
                "device": "/some/old/device/path",
            },
        },
        {"Driver": "local", "Options": {"type": "volume"}},
    ]
    for record in records:
        encoded = json.dumps([record]).encode()
        mock_capture, mock_full, commands = _mock_volume_commands((0, encoded, b""))
        with mock_capture, mock_full:
            with pytest.raises(Exception) as exc_info:
                app._reconcile_managed_volumes()
        # The colliding volume is never removed, and the user is told it is
        # protected and how to remove it by hand.
        assert _removed_volumes(commands) == []
        message = str(exc_info.value)
        assert "hm_test_app_myvol" in message
        assert "not a Harbormaster-managed volume" in message
        assert "collides" in message
        assert "protected" in message
        assert "docker volume rm hm_test_app_myvol" in message


def test_reconcile_managed_volumes_labelled_stale_record_repointed(
    tmpdir: Path,
) -> None:
    app = _make_managed_app(tmpdir)
    stale_record = json.dumps(
        [
            {
                "Driver": "local",
                "Labels": {"com.harbormaster.app": "test_app"},
                "Options": {
                    "type": "none",
                    "o": "bind",
                    "device": "/some/old/device/path",
                },
            }
        ]
    ).encode()
    mock_capture, mock_full, commands = _mock_volume_commands((0, stale_record, b""))
    with mock_capture, mock_full:
        app._reconcile_managed_volumes()
    # The record is ours, so it is only bookkeeping: it is removed and
    # `docker compose up` will recreate it pointing at the new device path.
    assert _inspected_volumes(commands) == ["hm_test_app_myvol"]
    assert _removed_volumes(commands) == ["hm_test_app_myvol"]


def test_reconcile_managed_volumes_failed_removal_raises(tmpdir: Path) -> None:
    app = _make_managed_app(tmpdir)
    stale_record = json.dumps(
        [
            {
                "Driver": "local",
                "Labels": {"com.harbormaster.app": "test_app"},
                "Options": {
                    "type": "none",
                    "o": "bind",
                    "device": "/some/old/device/path",
                },
            }
        ]
    ).encode()
    commands = []

    def fake_capture(
        command: List[Union[str, Path]], **kwargs: Any
    ) -> Tuple[int, bytes, bytes]:
        commands.append(command)
        return (0, stale_record, b"")

    def fake_run_command_full(
        command: List[Union[str, Path]],
        chdir: Path,
        environment: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> Tuple[int, bytes]:
        commands.append(command)
        return (1, b"Error response from daemon: volume is in use")

    with patch(
        "docker_harbormaster.cli._run_command_capture_output",
        side_effect=fake_capture,
    ):
        with patch(
            "docker_harbormaster.cli._run_command_full",
            side_effect=fake_run_command_full,
        ):
            with pytest.raises(Exception) as exc_info:
                app._reconcile_managed_volumes()

    # The stale labelled record is removed, and a failed removal raises with
    # the volume named and instructions for releasing it.
    assert _removed_volumes(commands) == ["hm_test_app_myvol"]
    message = str(exc_info.value)
    assert "hm_test_app_myvol" in message
    assert "test_app" in message
    assert "docker compose down" in message
    assert "volume is in use" in message


def test_reconcile_managed_volumes_uses_app_environment(tmpdir: Path) -> None:
    app = _make_managed_app(tmpdir)
    # An app's DOCKER_HOST must reach the volume commands: inspecting a
    # different daemon than `docker compose up` talks to would silently bypass
    # the collision protection, which refuses unlabelled volumes on the daemon
    # that actually holds them.
    app.environment["DOCKER_HOST"] = "tcp://127.0.0.1:2375"
    stale_record = json.dumps(
        [
            {
                "Driver": "local",
                "Labels": {"com.harbormaster.app": "test_app"},
                "Options": {
                    "type": "none",
                    "o": "bind",
                    "device": "/some/old/device/path",
                },
            }
        ]
    ).encode()
    capture_environments = []
    full_environments = []

    def fake_capture(
        command: List[Union[str, Path]], **kwargs: Any
    ) -> Tuple[int, bytes, bytes]:
        capture_environments.append(kwargs.get("environment"))
        return (0, stale_record, b"")

    def fake_run_command_full(
        command: List[Union[str, Path]], chdir: Path, **kwargs: Any
    ) -> Tuple[int, bytes]:
        full_environments.append(kwargs.get("environment"))
        return (0, b"")

    with patch(
        "docker_harbormaster.cli._run_command_capture_output",
        side_effect=fake_capture,
    ):
        with patch(
            "docker_harbormaster.cli._run_command_full",
            side_effect=fake_run_command_full,
        ):
            app._reconcile_managed_volumes()

    # The stale labelled record is inspected and then removed, and both
    # commands carry the app's DOCKER_HOST, so they hit the same daemon as
    # `docker compose up`.
    assert capture_environments == [app.environment]
    assert full_environments == [app.environment]


def test_kill_orphan_containers_filters_by_working_dir_label(tmpdir: Path) -> None:
    # Compose v2 labels every container it creates with the absolute path of
    # the directory holding its first compose file, so containers are listed
    # together with that label and only the ones whose label is the app's
    # repo directory or inside it are stopped and removed; `-a` includes
    # stopped containers, which hold volume references too, so they are
    # stopped gracefully first and then removed to release the references
    # without force-killing.
    repo_dir = Path(tmpdir) / "repos" / "test_app"
    mock, commands = _mock_docker_commands((0, f"abc123 {repo_dir}\n".encode()))
    with mock:
        cli._kill_orphan_containers(repo_dir)
    assert commands[0] == [
        "/usr/bin/env",
        "docker",
        "ps",
        "-a",
        "--format",
        '{{.ID}} {{.Label "com.docker.compose.project.working_dir"}}',
    ]
    assert [command[2] for command in commands[1:]] == ["stop", "rm"]
    assert commands[1][3] == commands[2][3] == "abc123"


def test_kill_orphan_containers_does_not_touch_prefix_matching_app(
    tmpdir: Path,
) -> None:
    # A stale app `foo` and a live app `foo-bar` have sibling project
    # directories that both appear in the listing, and the label containment
    # check compares path components rather than string prefixes, so cleaning
    # up `foo` stops and removes only `foo`'s own containers and never even
    # touches `foo-bar`'s.
    paths = Paths.for_workdir(Path(tmpdir), config_dir=Path(tmpdir))
    paths.create_directories()
    mock, commands = _mock_docker_ps_working_dir_listing(
        {
            paths.repos_dir / "foo": ["stale_web_1"],
            paths.repos_dir / "foo-bar": ["live_web_1", "live_db_1"],
        }
    )
    with mock:
        cli._kill_orphan_containers(paths.repos_dir / "foo")
    # Only the stale app's container is stopped and removed, and never
    # the live app's, even though both appear in the same listing.
    assert [command[2] for command in commands[1:]] == ["stop", "rm"]
    assert [command[3] for command in commands[1:]] == [
        "stale_web_1",
        "stale_web_1",
    ]


def test_kill_orphan_containers_nested_compose_config_path(tmpdir: Path) -> None:
    # An app whose compose_config points below its repo directory, like the
    # bundled `apps/ztncui/docker-compose.harbormaster.yml` shape, gets a
    # working_dir label on the nested directory holding the compose file, not
    # on the repo directory itself, so the containment check must accept
    # label paths inside the repo directory. Containers of a
    # prefix-colliding sibling app and containers without the label at all
    # must still be ignored.
    paths = Paths.for_workdir(Path(tmpdir), config_dir=Path(tmpdir))
    paths.create_directories()
    repo_dir = paths.repos_dir / "app"
    mock, commands = _mock_docker_ps_working_dir_listing(
        {
            repo_dir: ["root_web_1"],
            repo_dir / "apps" / "ztncui": ["nested_web_1"],
            paths.repos_dir / "app-other": ["other_web_1"],
        },
        unlabelled=["unlabelled_web_1"],
    )
    with mock:
        cli._kill_orphan_containers(repo_dir)
    # Both the container labelled with the repo directory and the one
    # labelled with the nested compose directory are stopped and removed,
    # while the sibling app's and the unlabelled containers are not.
    assert [command[3] for command in commands[1:]] == [
        "root_web_1",
        "root_web_1",
        "nested_web_1",
        "nested_web_1",
    ]


def _make_stale_volume_paths(tmpdir: Path) -> Paths:
    """Return paths with a stale app's data directory in place."""
    tmpdir = Path(tmpdir)
    paths = Paths.for_workdir(tmpdir, config_dir=tmpdir)
    paths.create_directories()
    (paths.data_dir / "stale_app").mkdir()
    return paths


def _mock_volume_cleanup(
    records: Dict[str, Dict[str, Any]],
) -> Tuple[Any, Any, List[List[Union[str, Path]]], List[str]]:
    """Return mocks for the capture helper and _run_command_full that simulate volume ls/inspect/rm."""
    commands = []
    removed = []

    def fake_capture(
        command: List[Union[str, Path]], **kwargs: Any
    ) -> Tuple[int, bytes, bytes]:
        commands.append(command)
        if command[:3] != ["/usr/bin/env", "docker", "volume"]:
            return (0, b"", b"")
        subcommand = command[3]
        if subcommand == "ls":
            # The mock honors the label filter exactly like `docker volume ls`
            # does, so only records carrying the requested label are listed.
            filter_label = command[command.index("--filter") + 1]
            # The filter we issue always carries a plain-string label.
            assert isinstance(filter_label, str)
            label_key, label_value = filter_label.split("=", 1)[1].split("=", 1)
            names = [
                name
                for name, record in records.items()
                if (record.get("Labels") or {}).get(label_key) == label_value
            ]
            return (0, "\n".join(names).encode() + b"\n", b"")
        volume_name = command[4]
        # The volume commands we issue always carry plain-string names.
        assert isinstance(volume_name, str)
        if subcommand == "inspect":
            return (0, json.dumps([records[volume_name]]).encode(), b"")
        return (0, b"", b"")

    def fake_run_command_full(
        command: List[Union[str, Path]],
        chdir: Path,
        environment: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> Tuple[int, bytes]:
        commands.append(command)
        if command[:3] == ["/usr/bin/env", "docker", "volume"]:
            subcommand = command[3]
            if subcommand == "rm":
                volume_name = command[4]
                # The volume commands we issue always carry plain-string names.
                assert isinstance(volume_name, str)
                removed.append(volume_name)
                return (0, b"")
        return (0, b"")

    return (
        patch(
            "docker_harbormaster.cli._run_command_capture_output",
            side_effect=fake_capture,
        ),
        patch(
            "docker_harbormaster.cli._run_command_full",
            side_effect=fake_run_command_full,
        ),
        commands,
        removed,
    )


def test_archive_stale_data_removes_labelled_volume_inside_data(tmpdir: Path) -> None:
    paths = _make_stale_volume_paths(tmpdir)
    records = {
        "hm_stale_app_myvol": {
            "Driver": "local",
            "Labels": {"com.harbormaster.app": "stale_app"},
            "Options": {
                "type": "none",
                "o": "bind",
                "device": str(paths.data_dir / "stale_app" / "myvol"),
            },
        }
    }
    mock_capture, mock_full, commands, removed = _mock_volume_cleanup(records)
    with mock_capture, mock_full:
        cli.archive_stale_data([], paths)
    # The record carrying the stale app's label and pointing inside the data
    # tree is verified and then removed.
    assert removed == ["hm_stale_app_myvol"]
    assert _volume_ls_label_filters(commands) == [
        "label=com.harbormaster.app=stale_app"
    ]


def test_archive_stale_data_leaves_labelled_volume_outside_workdir(
    tmpdir: Path,
) -> None:
    paths = _make_stale_volume_paths(tmpdir)
    records = {
        "hm_stale_app_myvol": {
            "Driver": "local",
            "Labels": {"com.harbormaster.app": "stale_app"},
            "Options": {
                "type": "none",
                "o": "bind",
                "device": "/somewhere/else/entirely",
            },
        }
    }
    mock_capture, mock_full, commands, removed = _mock_volume_cleanup(records)
    with mock_capture, mock_full:
        cli.archive_stale_data([], paths)
    # The record is found and inspected, but never removed: its device points
    # outside the workdir, so its data is not ours to discard.
    assert _inspected_volumes(commands) == ["hm_stale_app_myvol"]
    assert _removed_volumes(commands) == []
    assert _volume_ls_label_filters(commands) == [
        "label=com.harbormaster.app=stale_app"
    ]


def test_archive_stale_data_failed_volume_listing_skips_app(
    tmpdir: Path, capsys: Any
) -> None:
    paths = _make_stale_volume_paths(tmpdir)
    # An unreachable daemon must not abort the run: any Docker failure while
    # cleaning up a stale app warns and skips that app's filesystem cleanup,
    # so the listing failure reports the app as failed and leaves its
    # directories in place for the next run to retry.
    mock_capture, mock_full, commands = _mock_volume_commands(
        (
            1,
            b"",
            b"Cannot connect to the Docker daemon at "
            b"unix:///var/run/docker.sock. Is the docker daemon running?",
        )
    )
    with mock_capture, mock_full:
        success = cli._remove_stale_volume_records("stale_app", paths)
    # The app's cleanup is reported as failed, and no removal is attempted
    # once the listing has failed.
    assert success is False
    assert _volume_ls_label_filters(commands) == [
        "label=com.harbormaster.app=stale_app"
    ]
    assert _removed_volumes(commands) == []
    output = capsys.readouterr().out
    assert "stale_app" in output
    assert "docker daemon" in output
    assert "retried on the next run" in output


def test_archive_stale_data_volume_disappeared_between_listing_and_inspect(
    tmpdir: Path,
) -> None:
    paths = _make_stale_volume_paths(tmpdir)
    commands = []

    def fake_capture(
        command: List[Union[str, Path]], **kwargs: Any
    ) -> Tuple[int, bytes, bytes]:
        commands.append(command)
        if command[:3] != ["/usr/bin/env", "docker", "volume"]:
            return (0, b"", b"")
        subcommand = command[3]
        if subcommand == "ls":
            return (0, b"hm_stale_app_myvol\n", b"")
        if subcommand == "inspect":
            # The volume vanished between the listing and the inspection,
            # which is a genuine absence, so the cleanup moves on without
            # attempting a removal.
            return (1, b"", b"Error: No such volume: hm_stale_app_myvol")
        return (0, b"", b"")

    def fake_run_command_full(
        command: List[Union[str, Path]],
        chdir: Path,
        environment: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> Tuple[int, bytes]:
        commands.append(command)
        return (0, b"")

    with patch(
        "docker_harbormaster.cli._run_command_capture_output",
        side_effect=fake_capture,
    ):
        with patch(
            "docker_harbormaster.cli._run_command_full",
            side_effect=fake_run_command_full,
        ):
            # A volume that vanished between listing and inspection is a
            # genuine absence, not a failure, so the app's cleanup succeeds.
            success = cli._remove_stale_volume_records("stale_app", paths)

    assert success is True
    assert _inspected_volumes(commands) == ["hm_stale_app_myvol"]
    assert _removed_volumes(commands) == []


def test_archive_stale_data_failed_volume_removal_warns_and_continues(
    tmpdir: Path, capsys: Any
) -> None:
    paths = _make_stale_volume_paths(tmpdir)
    records = {
        "hm_stale_app_first": {
            "Driver": "local",
            "Labels": {"com.harbormaster.app": "stale_app"},
            "Options": {
                "type": "none",
                "o": "bind",
                "device": str(paths.data_dir / "stale_app" / "first"),
            },
        },
        "hm_stale_app_second": {
            "Driver": "local",
            "Labels": {"com.harbormaster.app": "stale_app"},
            "Options": {
                "type": "none",
                "o": "bind",
                "device": str(paths.data_dir / "stale_app" / "second"),
            },
        },
    }
    commands = []
    removed = []

    def fake_capture(
        command: List[Union[str, Path]], **kwargs: Any
    ) -> Tuple[int, bytes, bytes]:
        commands.append(command)
        if command[:3] != ["/usr/bin/env", "docker", "volume"]:
            return (0, b"", b"")
        subcommand = command[3]
        if subcommand == "ls":
            return (0, b"hm_stale_app_first\nhm_stale_app_second\n", b"")
        volume_name = command[4]
        # The volume commands we issue always carry plain-string names.
        assert isinstance(volume_name, str)
        if subcommand == "inspect":
            return (0, json.dumps([records[volume_name]]).encode(), b"")
        return (0, b"", b"")

    def fake_run_command_full(
        command: List[Union[str, Path]],
        chdir: Path,
        environment: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> Tuple[int, bytes]:
        commands.append(command)
        if command[:3] == ["/usr/bin/env", "docker", "volume"]:
            subcommand = command[3]
            volume_name = command[4]
            # The volume commands we issue always carry plain-string names.
            assert isinstance(volume_name, str)
            if subcommand == "rm":
                removed.append(volume_name)
                if volume_name == "hm_stale_app_first":
                    # The first removal fails, as it would when a container still
                    # references the volume.
                    return (1, b"Error response from daemon: volume is in use")
                return (0, b"")
        return (0, b"")

    with patch(
        "docker_harbormaster.cli._run_command_capture_output",
        side_effect=fake_capture,
    ):
        with patch(
            "docker_harbormaster.cli._run_command_full",
            side_effect=fake_run_command_full,
        ):
            # The failed removal must not raise: a leftover record is harmless
            # bookkeeping, so the cleanup moves on and removes the second record.
            cli.archive_stale_data([], paths)

    assert removed == ["hm_stale_app_first", "hm_stale_app_second"]
    # The warning names the volume whose removal failed.
    output = capsys.readouterr().out
    assert "hm_stale_app_first" in output
    assert "volume is in use" in output
    # One record is left behind, so the app's data directory must survive:
    # archiving it would drop the app from future scans and the retry the
    # warning promises would never happen.
    assert (paths.data_dir / "stale_app").is_dir()
    assert not list(paths.archives_dir.iterdir())


def test_archive_stale_data_failed_cleanup_leaves_app_untouched(
    tmpdir: Path, capsys: Any
) -> None:
    # A stale app whose volume record could not be removed keeps every one of
    # its directories so the next run genuinely retries, while a second stale
    # app in the same run is still cleaned up normally.
    paths = Paths.for_workdir(Path(tmpdir), config_dir=Path(tmpdir))
    paths.create_directories()
    for app_name in ("failed_app", "ok_app"):
        (paths.repos_dir / app_name).mkdir()
        (paths.data_dir / app_name).mkdir()
        (paths.caches_dir / app_name).mkdir()
    records: Dict[str, Dict[str, Any]] = {
        "hm_failed_app_myvol": {
            "Driver": "local",
            "Labels": {"com.harbormaster.app": "failed_app"},
            "Options": {
                "type": "none",
                "o": "bind",
                "device": str(paths.data_dir / "failed_app" / "myvol"),
            },
        }
    }
    commands = []
    removed = []
    rmtree_calls = []

    def fake_capture(
        command: List[Union[str, Path]], **kwargs: Any
    ) -> Tuple[int, bytes, bytes]:
        commands.append(command)
        if command[:3] != ["/usr/bin/env", "docker", "volume"]:
            return (0, b"", b"")
        subcommand = command[3]
        if subcommand == "ls":
            # The mock honors the label filter exactly like `docker volume ls`
            # does, so only records carrying the requested label are listed.
            filter_label = command[command.index("--filter") + 1]
            # The filter we issue always carries a plain-string label.
            assert isinstance(filter_label, str)
            label_key, label_value = filter_label.split("=", 1)[1].split("=", 1)
            names = [
                name
                for name, record in records.items()
                if (record.get("Labels") or {}).get(label_key) == label_value
            ]
            return (0, "\n".join(names).encode() + b"\n", b"")
        volume_name = command[4]
        # The volume commands we issue always carry plain-string names.
        assert isinstance(volume_name, str)
        if subcommand == "inspect":
            return (0, json.dumps([records[volume_name]]).encode(), b"")
        return (0, b"", b"")

    def fake_run_command_full(
        command: List[Union[str, Path]],
        chdir: Path,
        environment: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> Tuple[int, bytes]:
        commands.append(command)
        if command[:3] == ["/usr/bin/env", "docker", "volume"]:
            subcommand = command[3]
            volume_name = command[4]
            # The volume commands we issue always carry plain-string names.
            assert isinstance(volume_name, str)
            if subcommand == "rm":
                removed.append(volume_name)
                # The removal fails, as it would when a container still
                # references the volume.
                return (1, b"Error response from daemon: volume is in use")
        return (0, b"")

    real_rmtree = shutil.rmtree

    def fake_rmtree(path: Path, *args: Any, **kwargs: Any) -> None:
        rmtree_calls.append(Path(path))
        # Delegate to the real removal so the surviving directories are the
        # ones the code actually left alone.
        real_rmtree(path, *args, **kwargs)

    with patch(
        "docker_harbormaster.cli._run_command_capture_output",
        side_effect=fake_capture,
    ):
        with patch(
            "docker_harbormaster.cli._run_command_full",
            side_effect=fake_run_command_full,
        ):
            with patch(
                "docker_harbormaster.cli.shutil.rmtree", side_effect=fake_rmtree
            ):
                cli.archive_stale_data([], paths)

    # failed_app's record is still in place, so none of its directories are
    # touched, neither by rmtree nor by the data-dir rename.
    assert (paths.repos_dir / "failed_app").is_dir()
    assert (paths.data_dir / "failed_app").is_dir()
    assert (paths.caches_dir / "failed_app").is_dir()
    assert rmtree_calls == [paths.repos_dir / "ok_app", paths.caches_dir / "ok_app"]
    # ok_app is cleaned up normally: its repo and caches are gone and its data
    # has been moved into the archives.
    assert not (paths.repos_dir / "ok_app").exists()
    assert not (paths.caches_dir / "ok_app").exists()
    assert not (paths.data_dir / "ok_app").exists()
    archived = list(paths.archives_dir.iterdir())
    assert len(archived) == 1
    assert archived[0].name.startswith("ok_app-")
    # The warning names the failing app so the user knows why its cleanup was
    # skipped.
    output = capsys.readouterr().out
    assert "failed_app" in output
    assert "volume is in use" in output
