from pathlib import Path

import pytest
import yaml

from docker_harbormaster.cli import _read_var_file
from docker_harbormaster.cli import _render_template


def test_template():
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
        assert _render_template(template, replacements) == result


def test_var_reading(tmpdir):
    tmpdir = Path(tmpdir)

    filename = tmpdir / "env.yaml"

    d = {"FOO": "bar", "BAZ": "3"}
    with open(filename, "w") as outfile:
        outfile.write(yaml.safe_dump(d))
    assert _read_var_file(filename, tmpdir, "id") == d

    # Dump the file improperly, with ints as ints instead of strings.
    with open(filename, "w") as outfile:
        outfile.write("\n".join(f"{key}: {value}" for key, value in d.items()))
    with pytest.raises(ValueError):
        _read_var_file(filename, tmpdir, "id")

    with open(filename, "w") as outfile:
        outfile.write("- 1\n- 2")
    with pytest.raises(ValueError):
        _read_var_file(filename, tmpdir, "id")

    with open(filename, "w") as outfile:
        outfile.write("foo: 1\nbar:\n  - 1\n  - 2")
    with pytest.raises(ValueError):
        _read_var_file(filename, tmpdir, "id")

    filename = tmpdir / "env.txt"

    d = {"FOO": "bar", "BAZ": "3"}
    with open(filename, "w") as outfile:
        outfile.write("\n".join(f"{key}={value}" for key, value in d.items()))
    assert _read_var_file(filename, tmpdir, "id") == d
