#!/usr/bin/env bash
set -euo pipefail
cd /home/agent/work/discourse-sql-ft
uv run python scripts/add_builtin_queries_reports_pack.py
