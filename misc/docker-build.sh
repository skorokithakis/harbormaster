#!/usr/bin/env bash

set -eux

cd "$(dirname "$0")"
cd ..

# Get the version either from CI_COMMIT_TAG if it's defined (ie on CI), or from the
# pyproject.toml otherwise (ie locally).
IMAGE_VERSION="${CI_COMMIT_TAG:-$(sed -n 's/version *= *"\(.*\)\"/\1/p' pyproject.toml)}"
IMAGE_BASE=stavros/harbormaster
IMAGE_NAME=$IMAGE_BASE:$IMAGE_VERSION
TMP_DIR=$(mktemp -d)

sed "s/IMAGE_VERSION/$IMAGE_VERSION/g" misc/Dockerfile > "$TMP_DIR/Dockerfile"

echo "Building $IMAGE_NAME..."
docker build -f "$TMP_DIR/Dockerfile" -t "$IMAGE_NAME" -t "$IMAGE_BASE:latest" .

if [[ "${1-}" == "--push" ]]; then
    echo "Pushing $IMAGE_NAME..."
    docker push "$IMAGE_NAME"
    docker push "$IMAGE_BASE:latest"
fi
