from docker_harbormaster.cli import render_template


def test_template():
    replacements = {"FOO": 3, "BAR": 4}
    templates = [
        ("""{{ HM_FOO }}, {{ HM_BAR }}, {{ HM_BAZ:80 }}""", "3, 4, 80"),
        ("""{{ HM_FOO }} {{ HM_BAZ }}""", "3 {{ HM_BAZ }}"),
        ("""{{ HM_FOO }} {{ BAR }}""", "3 {{ BAR }}"),
        ("""{{ HM_BAR }}, {{ HM_BAZ:a } }}""", "4, HM_INVALID_DEFAULT_VALUE"),
        ("""{{ HM_BAR }}, {{ HM_BAZ:"hello" }}""", "4, hello"),
    ]
    for template, result in templates:
        assert render_template(template, replacements) == result
