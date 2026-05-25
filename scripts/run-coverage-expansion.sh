#!/usr/bin/env bash
set -euo pipefail
cd /home/agent/work/discourse-sql-ft
uv run python scripts/improve_table_coverage.py
