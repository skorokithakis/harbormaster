#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../"

docker build -f misc/Dockerfile.pyinstall -t stavros/harbormaster-install .

docker run -v "$(pwd)":/workdir stavros/harbormaster-install
