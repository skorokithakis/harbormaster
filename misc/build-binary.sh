#!/usr/bin/env bash
set -euo pipefail

poetry export --without-hashes -o requirements.txt

poetry config virtualenvs.create false

poetry install

pyinstaller --clean -y --dist dist/linux --workpath /tmp pyinstaller.spec
