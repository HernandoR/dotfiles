#!/usr/bin/env sh
set -e

echo "Starting bootstrap process..."

if ! command -v curl > /dev/null 2>&1; then
    echo "Error: curl is required to bootstrap. Please install curl first."
    exit 1
fi

if ! command -v uv > /dev/null 2>&1; then
    echo "uv not found. Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh

    if [ -f "$HOME/.local/bin/env" ]; then
        . "$HOME/.local/bin/env"
    else
        export PATH="$HOME/.local/bin:$PATH"
    fi
fi

echo "Handing off execution to Python via uv..."
uv run main.py "$@"
