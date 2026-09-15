#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/bootstrap.sh" --env mewtant "$@"
