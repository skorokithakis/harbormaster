#!/bin/sh

set -eu

cd "$(dirname "$0")/../"

# The release version is passed in explicitly by the caller; the release workflow
# takes it from release-please's output. Deriving it here from a git tag is
# unreliable in that workflow, since the tag is created seconds earlier by another
# job and isn't present in a fresh checkout. With no version only :latest and
# :webhook are built, which is the behaviour local, unversioned builds want.
IMAGE_VERSION=""
PUSH=0
for ARG in "$@"; do
    case "$ARG" in
        --push)
            PUSH=1
            ;;
        -*)
            echo "usage: $0 [<version>] [--push]" >&2
            exit 2
            ;;
        *)
            if [ -n "$IMAGE_VERSION" ]; then
                echo "usage: $0 [<version>] [--push]" >&2
                exit 2
            fi
            IMAGE_VERSION="$ARG"
            ;;
    esac
done
IMAGE_BASE=stavros/harbormaster

echo "Building images"
if [ -n "$IMAGE_VERSION" ]; then
    docker build -f misc/Dockerfile -t "$IMAGE_BASE:latest" -t "$IMAGE_BASE:$IMAGE_VERSION" .
    docker build -f misc/Dockerfile.webhook -t "$IMAGE_BASE:webhook" -t "$IMAGE_BASE:$IMAGE_VERSION-webhook" .
else
    docker build -f misc/Dockerfile -t "$IMAGE_BASE:latest" .
    docker build -f misc/Dockerfile.webhook -t "$IMAGE_BASE:webhook" .
fi

if [ "$PUSH" = 1 ]; then
    echo "Pushing images"
    docker push --all-tags "$IMAGE_BASE"
fi
