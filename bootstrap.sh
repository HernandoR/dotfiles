#!/usr/bin/env bash
# Entry point → the imperative bootstrap layer. See platform/README.md and
# docs/plans/adr-0007 for the design. All arguments are forwarded.
#
#   ./bootstrap.sh --dry-run          # preview
#   ./bootstrap.sh --yes              # skip the interactive plan clearance
#   ./bootstrap.sh --network CN       # enable China mirrors
#   ./bootstrap.sh --system docker    # + Linux system components
#
# On a terminal it prints the full plan (installs · network · config written and
# linked) and asks for clearance once; with no terminal it never asks.
exec "$(cd "$(dirname "$0")" && pwd)/platform/bootstrap.sh" "$@"
