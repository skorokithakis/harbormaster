#!/bin/sh

set -eu

cd "$(dirname "$0")/../"

# Get the version from pyproject.toml. No CI job builds these images; releases are
# made by hand, so the declared version is the only source of truth. Do not reach for
# GITHUB_REF_NAME here if this is ever automated: unlike GitLab's CI_COMMIT_TAG, it is
# also set on branch pushes, and would tag an image `master`.
# The anchor matters: without it this also matches ruff's `target-version`.
IMAGE_VERSION="$(sed -n 's/^version *= *"\(.*\)"/\1/p' pyproject.toml)"
IMAGE_BASE=stavros/harbormaster

echo "Building images"
docker build -f misc/Dockerfile -t "$IMAGE_BASE:$IMAGE_VERSION" -t "$IMAGE_BASE:latest" .
docker build -f misc/Dockerfile.webhook -t "$IMAGE_BASE:${IMAGE_VERSION}-webhook" -t "$IMAGE_BASE:webhook" .

if [ "${1-}" = "--push" ]; then
    echo "Pushing images"
    docker push --all-tags "$IMAGE_BASE"
fi
