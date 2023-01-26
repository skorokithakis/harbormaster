#!/bin/sh

set -eu

cd "$(dirname "$0")/../"

# Get the version either from CI_COMMIT_TAG if it's defined (ie on CI), or from the
# pyproject.toml otherwise (ie locally).
IMAGE_VERSION="${CI_COMMIT_TAG:-$(sed -n 's/version *= *"\(.*\)\"/\1/p' pyproject.toml)}"
IMAGE_BASE=stavros/harbormaster

echo "Building images"
docker build -f misc/Dockerfile -t "$IMAGE_BASE:$IMAGE_VERSION" -t "$IMAGE_BASE:latest" .
docker build -f misc/Dockerfile.webhook -t "$IMAGE_BASE:${IMAGE_VERSION}-webhook" -t "$IMAGE_BASE:webhook" .

if [ "${1-}" = "--push" ]; then
    echo "Pushing images"
    docker push --all-tags "$IMAGE_BASE"
fi
