#!/usr/bin/env bash

set -euox pipefail

cd /config/
/usr/bin/git pull
/usr/local/bin/harbormaster -d /main -c /config/harbormaster.yml
