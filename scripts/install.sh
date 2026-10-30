#!/usr/bin/env sh
set -eu
target="${1:-$(pwd)}"
shift || true
exec python3 "$(dirname "$0")/install.py" --target "$target" "$@"
