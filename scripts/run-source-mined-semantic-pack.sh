#!/usr/bin/env bash
set -euo pipefail
cd /home/agent/work/discourse-sql-ft
uv run python scripts/add_source_mined_semantic_pack.py
