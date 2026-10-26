#!/usr/bin/env bash
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { echo "Run: bash install.sh  first"; exit 1; }
.venv/bin/python server.py
