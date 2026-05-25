#!/usr/bin/env bash
set -euo pipefail
cd /home/agent/work/discourse-sql-ft
exec uv run python scripts/supervisor.py "$@"
