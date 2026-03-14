#!/usr/bin/env sh
set -e
python -m pip install -r requirements.txt
pytest -q
