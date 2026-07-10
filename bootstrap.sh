#!/usr/bin/env bash
# Entry point → the imperative bootstrap layer. See platform/README.md and
# docs/plans/adr-0007 for the design. All arguments are forwarded.
#
#   ./bootstrap.sh --dry-run          # preview
#   ./bootstrap.sh --network CN       # enable China mirrors
#   ./bootstrap.sh --system docker    # + Linux system components
exec "$(cd "$(dirname "$0")" && pwd)/platform/bootstrap.sh" "$@"
