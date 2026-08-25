# Notes for agents

## Keep the agent guide current

`docs/source/_extra/llms.txt` is a single-page guide for LLM agents that set up
a Harbormaster deployment for a user. When a change affects how someone uses
Harbormaster, update that file in the same change. That includes config file keys,
Compose file discovery, volume handling, the CLI commands and their options, and the
layout of the working directory.

It is published verbatim at
https://harbormaster.readthedocs.io/en/latest/llms.txt, so it must stay accurate on
its own, without the rest of the documentation.

## Conventions

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/).
release-please reads them to decide version bumps and to write `CHANGELOG.md`, so the
type prefix matters (`feat:`, `fix:`, `chore:`, `docs:`, and `!` for a breaking change).

Linting and type checking live in `.pre-commit-config.yaml` (ruff and mypy). Tests are
pytest, under `tests/`.
