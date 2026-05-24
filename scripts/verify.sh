#!/usr/bin/env bash
set -euo pipefail

python_bin="${PYTHON:-.venv/bin/python}"
"${python_bin}" -m coverage run --source=src -m unittest discover -s tests -t .
"${python_bin}" -m coverage report -m --fail-under=85
