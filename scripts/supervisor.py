#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

import yaml

ROOT = Path('/home/agent/work/discourse-sql-ft')
CONFIG_PATH = ROOT / 'config' / 'experiment.yaml'
STATE_PATH = ROOT / 'state' / 'supervisor.json'
STATUS_MD = ROOT / 'STATUS.md'
LOG_PATH = ROOT / 'logs' / 'supervisor.log'
LOCK_PATH = ROOT / 'state' / 'locks' / 'supervisor.lock'


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def log(msg: str) -> None:
    line = f"{utcnow()} {msg}"
    print(line, flush=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open('a', encoding='utf-8') as f:
        f.write(line + '\n')


def load_config() -> dict:
    with CONFIG_PATH.open('r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def initial_state(config: dict) -> dict:
    phases = config['phases']
    return {
        'experiment': config['experiment']['name'],
        'status': 'initialized',
        'current_phase': phases[0] if phases else None,
        'started_at': None,
        'updated_at': utcnow(),
        'finished_at': None,
        'last_error': None,
        'phases': {
            name: {
                'status': 'pending',
                'started_at': None,
                'finished_at': None,
                'attempts': 0,
                'last_run_log': None,
                'error': None,
            } for name in phases
        },
    }


def load_state(config: dict) -> dict:
    if not STATE_PATH.exists():
        state = initial_state(config)
        save_state(state)
        return state
    with STATE_PATH.open('r', encoding='utf-8') as f:
        return json.load(f)


def save_state(state: dict) -> None:
    state['updated_at'] = utcnow()
    tmp = STATE_PATH.with_suffix('.json.tmp')
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)
        f.write('\n')
    os.replace(tmp, STATE_PATH)
    write_status_md(state)


def write_status_md(state: dict) -> None:
    lines = []
    lines.append('# Discourse SQL FT Status')
    lines.append('')
    lines.append(f"- Experiment: `{state['experiment']}`")
    lines.append(f"- Status: **{state['status']}**")
    lines.append(f"- Current phase: `{state.get('current_phase')}`")
    lines.append(f"- Updated: `{state.get('updated_at')}` UTC")
    if state.get('last_error'):
        lines.append(f"- Last error: `{state['last_error']}`")
    lines.append('')
    lines.append('| Phase | Status | Attempts | Started | Finished | Error |')
    lines.append('|---|---:|---:|---|---|---|')
    for name, phase in state['phases'].items():
        err = phase.get('error') or ''
        if len(err) > 80:
            err = err[:77] + '...'
        lines.append(
            f"| `{name}` | **{phase['status']}** | {phase['attempts']} | "
            f"{phase.get('started_at') or ''} | {phase.get('finished_at') or ''} | {err} |"
        )
    lines.append('')
    lines.append('## Logs')
    lines.append('')
    lines.append('- Supervisor: `logs/supervisor.log`')
    lines.append('- Phase logs: `logs/<phase>.log`')
    lines.append('')
    STATUS_MD.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def next_pending_phase(config: dict, state: dict) -> str | None:
    for phase in config['phases']:
        if state['phases'][phase]['status'] not in ('succeeded', 'skipped'):
            return phase
    return None


def phase_script(phase: str) -> Path:
    return ROOT / 'scripts' / 'phases' / f'{phase}.py'


def run_phase(phase: str, state: dict) -> None:
    script = phase_script(phase)
    phase_state = state['phases'][phase]
    phase_state['status'] = 'running'
    phase_state['started_at'] = utcnow()
    phase_state['finished_at'] = None
    phase_state['attempts'] += 1
    phase_state['error'] = None
    state['status'] = 'running'
    state['current_phase'] = phase
    if state['started_at'] is None:
        state['started_at'] = utcnow()
    save_state(state)

    log(f"starting phase={phase} script={script}")
    if not script.exists():
        raise RuntimeError(f"phase script missing: {script}")

    phase_log = ROOT / 'logs' / f'{phase}.log'
    phase_state['last_run_log'] = str(phase_log.relative_to(ROOT))
    save_state(state)

    with phase_log.open('a', encoding='utf-8') as f:
        f.write(f"\n===== {utcnow()} start {phase} =====\n")
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(ROOT),
            stdout=f,
            stderr=subprocess.STDOUT,
            text=True,
        )
        f.write(f"===== {utcnow()} end {phase} exit={proc.returncode} =====\n")

    if proc.returncode != 0:
        raise RuntimeError(f"phase {phase} failed with exit code {proc.returncode}; see {phase_log}")

    phase_state['status'] = 'succeeded'
    phase_state['finished_at'] = utcnow()
    phase_state['error'] = None
    save_state(state)
    log(f"finished phase={phase}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true', help='run only one pending phase')
    parser.add_argument('--status', action='store_true', help='print state and exit')
    args = parser.parse_args()

    config = load_config()
    state = load_state(config)

    if args.status:
        print(json.dumps(state, indent=2))
        write_status_md(state)
        return 0

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open('w') as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log('supervisor already running; exiting')
            return 0

        try:
            while True:
                phase = next_pending_phase(config, state)
                if phase is None:
                    state['status'] = 'succeeded'
                    state['current_phase'] = None
                    state['finished_at'] = utcnow()
                    state['last_error'] = None
                    save_state(state)
                    log('all phases complete')
                    return 0

                run_phase(phase, state)
                if args.once:
                    next_phase = next_pending_phase(config, state)
                    if next_phase is None:
                        state['status'] = 'succeeded'
                        state['current_phase'] = None
                        state['finished_at'] = utcnow()
                    else:
                        state['status'] = 'waiting'
                        state['current_phase'] = next_phase
                    state['last_error'] = None
                    save_state(state)
                    return 0

        except Exception as e:
            err = str(e)
            log(f'ERROR: {err}')
            log(traceback.format_exc())
            state['status'] = 'failed'
            state['last_error'] = err
            phase = state.get('current_phase')
            if phase and phase in state['phases']:
                state['phases'][phase]['status'] = 'failed'
                state['phases'][phase]['finished_at'] = utcnow()
                state['phases'][phase]['error'] = err
            save_state(state)
            return 1


if __name__ == '__main__':
    raise SystemExit(main())
