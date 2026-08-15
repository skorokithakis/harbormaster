#!/bin/sh

set -eu

cd "$(dirname "$0")/../"

# CI publishes both master and v* tag pushes. Apply a version tag only when HEAD is
# exactly tagged with a v* release tag; branch pushes and local builds get only
# :latest and :webhook. Read the tag from git, not GITHUB_REF_NAME (which is also
# set for branch pushes), and never fall back to the version in pyproject.toml.
if RELEASE_TAG="$(git describe --tags --exact-match --match 'v*' 2>/dev/null)"; then
    IMAGE_VERSION="${RELEASE_TAG#v}"
else
    IMAGE_VERSION=""
fi
IMAGE_BASE=stavros/harbormaster

echo "Building images"
if [ -n "$IMAGE_VERSION" ]; then
    docker build -f misc/Dockerfile -t "$IMAGE_BASE:latest" -t "$IMAGE_BASE:$IMAGE_VERSION" .
    docker build -f misc/Dockerfile.webhook -t "$IMAGE_BASE:webhook" -t "$IMAGE_BASE:$IMAGE_VERSION-webhook" .
else
    docker build -f misc/Dockerfile -t "$IMAGE_BASE:latest" .
    docker build -f misc/Dockerfile.webhook -t "$IMAGE_BASE:webhook" .
fi

if [ "${1-}" = "--push" ]; then
    echo "Pushing images"
    docker push --all-tags "$IMAGE_BASE"
fi
