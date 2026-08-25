import ast
from pathlib import Path


def test_llms_txt_documents_app_configuration_keys() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    app_source = (repository_root / "docker_harbormaster" / "cli.py").read_text()
    guide_text = (
        repository_root / "docs" / "source" / "_extra" / "llms.txt"
    ).read_text()

    module = ast.parse(app_source)
    app_class = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "App"
    )
    initializer = next(
        node
        for node in app_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    )

    configuration_keys = set()
    for node in ast.walk(initializer):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "configuration"
            and node.func.attr == "get"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            configuration_keys.add(node.args[0].value)
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "configuration"
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            configuration_keys.add(node.slice.value)
    assert configuration_keys, (
        "The configuration extraction shape in App.__init__ changed; this test needs "
        "updating."
    )
    assert {"url", "manage_volumes"} <= configuration_keys, (
        "The configuration extraction shape in App.__init__ changed; this test needs "
        "updating."
    )

    guide_lines = guide_text.splitlines()

    for key in configuration_keys:
        assert any(
            line.startswith("- `") and f"`{key}`" in line for line in guide_lines
        ), (
            f"App configuration key {key!r} is missing; fix it by documenting it "
            "in docs/source/_extra/llms.txt."
        )
