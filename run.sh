#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

export PYTHONPATH="${PYTHONPATH:-}:$(pwd)/src"
export TRADING_CONFIG="${TRADING_CONFIG:-config/trading.yaml}"

python3 src/main.py
