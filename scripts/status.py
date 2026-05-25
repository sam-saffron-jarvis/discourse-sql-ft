#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path('/home/agent/work/discourse-sql-ft')
STATE = ROOT / 'state' / 'supervisor.json'
STATUS = ROOT / 'STATUS.md'

if not STATE.exists():
    print('No supervisor state yet. Run scripts/run-supervisor.sh --status or the supervisor job once.')
    raise SystemExit(0)

state = json.loads(STATE.read_text())
print(f"Experiment: {state['experiment']}")
print(f"Status:     {state['status']}")
print(f"Current:    {state.get('current_phase')}")
print(f"Updated:    {state.get('updated_at')} UTC")
if state.get('last_error'):
    print(f"Error:      {state['last_error']}")
print()
print(f"{'Phase':22} {'Status':10} {'Attempts':8} {'Log'}")
print('-' * 72)
for name, phase in state['phases'].items():
    print(f"{name:22} {phase['status']:10} {phase['attempts']:<8} {phase.get('last_run_log') or ''}")
print()
print(f"Markdown status: {STATUS}")
