#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import platform
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from common import ROOT, fail, load_config, ok, print_report, run, warn, write_json

REPORT_JSON = ROOT / 'reports' / 'preflight.json'
REPORT_MD = ROOT / 'reports' / 'preflight.md'


def check_command(name: str, required: bool = True) -> dict[str, str]:
    path = shutil.which(name)
    if path:
        return ok(f'command:{name}', path)
    return (fail if required else warn)(f'command:{name}', 'not found in PATH')


def command_version(name: str, args: list[str], timeout: int = 10) -> str:
    try:
        cp = run([name, *args], timeout=timeout)
        out = (cp.stdout or cp.stderr).strip().splitlines()
        return out[0] if out else f'exit={cp.returncode}'
    except Exception as e:
        return f'error: {e}'


def check_disk(path: Path, min_free_gb: int) -> dict[str, str]:
    usage = shutil.disk_usage(path)
    free_gb = usage.free / (1024 ** 3)
    total_gb = usage.total / (1024 ** 3)
    detail = f'{free_gb:.1f} GiB free / {total_gb:.1f} GiB total at {path}'
    if free_gb >= min_free_gb:
        return ok('disk space', detail)
    return fail('disk space', f'{detail}; need at least {min_free_gb} GiB for model/training artifacts')


def check_python_module(name: str, required: bool = False) -> dict[str, str]:
    spec = importlib.util.find_spec(name)
    if spec:
        return ok(f'python module:{name}', 'importable')
    return (fail if required else warn)(f'python module:{name}', 'not installed yet')


def check_nvidia() -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    if not shutil.which('nvidia-smi'):
        return [fail('nvidia-smi', 'not found; cannot verify GPU')]

    cp = run(['nvidia-smi', '--query-gpu=name,memory.total,memory.free,driver_version', '--format=csv,noheader,nounits'], timeout=15)
    if cp.returncode != 0:
        return [fail('nvidia-smi', cp.stderr.strip() or cp.stdout.strip())]

    lines = [l.strip() for l in cp.stdout.splitlines() if l.strip()]
    if not lines:
        return [fail('gpu', 'nvidia-smi returned no GPUs')]

    for i, line in enumerate(lines):
        parts = [p.strip() for p in line.split(',')]
        if len(parts) >= 4:
            name, total_mb, free_mb, driver = parts[:4]
            try:
                total = int(total_mb)
                free = int(free_mb)
            except ValueError:
                checks.append(warn(f'gpu:{i}', f'unparseable nvidia-smi line: {line}'))
                continue
            detail = f'{name}; {free/1024:.1f}/{total/1024:.1f} GiB free; driver {driver}'
            if total >= 20_000:
                checks.append(ok(f'gpu:{i}', detail))
            else:
                checks.append(fail(f'gpu:{i}', detail + '; expected ~24 GiB class GPU for Qwen3.5-9B QLoRA'))
        else:
            checks.append(warn(f'gpu:{i}', line))
    return checks


def check_ollama_models() -> dict[str, str]:
    if not shutil.which('ollama'):
        return warn('ollama', 'not found; optional only')
    cp = run(['ollama', 'list'], timeout=20)
    if cp.returncode != 0:
        return warn('ollama list', cp.stderr.strip() or 'failed')
    qwen_lines = [l for l in cp.stdout.splitlines() if 'qwen' in l.lower()]
    if qwen_lines:
        return ok('ollama qwen models', '; '.join(qwen_lines[:3]))
    return warn('ollama qwen models', 'no local qwen models listed; fine-tune will use Hugging Face stack')


def check_jobs() -> dict[str, str]:
    if not shutil.which('term-llm'):
        return fail('term-llm', 'not found')
    cp = run(['term-llm', 'jobs', 'get', 'discourse-sql-ft-supervisor'], timeout=20)
    if cp.returncode == 0 and 'discourse-sql-ft-supervisor' in cp.stdout:
        return ok('jobs supervisor registration', 'discourse-sql-ft-supervisor exists')
    return fail('jobs supervisor registration', cp.stderr.strip() or cp.stdout.strip() or 'job not found')


def check_model_names(config: dict) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    primary = config['model']['primary']
    fallback = config['model']['fallback']
    if primary == 'Qwen/Qwen3.5-9B':
        checks.append(ok('primary model', primary))
    else:
        checks.append(warn('primary model', primary))
    if fallback == 'Qwen/Qwen3.5-9B-Base':
        checks.append(ok('fallback model', fallback))
    else:
        checks.append(warn('fallback model', fallback))
    return checks


def write_markdown(checks: list[dict[str, str]]) -> None:
    lines = ['# Preflight Report', '']
    lines.append('| Status | Item | Detail |')
    lines.append('|---|---|---|')
    for c in checks:
        lines.append(f"| {c['status']} | `{c['item']}` | {c.get('detail','').replace('|', '\\|')} |")
    lines.append('')
    failures = [c for c in checks if c['status'] == 'fail']
    warnings = [c for c in checks if c['status'] == 'warn']
    lines.append(f'- Failures: {len(failures)}')
    lines.append(f'- Warnings: {len(warnings)}')
    REPORT_MD.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main() -> int:
    config = load_config()
    checks: list[dict[str, str]] = []

    checks.append(ok('root', str(ROOT)))
    checks.append(ok('python', f'{platform.python_version()} at {sys.executable}'))
    checks.append(check_command('uv'))
    checks.append(check_command('python'))
    checks.append(check_command('psql', required=False))
    checks.append(check_command('pg_dump', required=False))
    checks.append(check_command('git'))
    checks.append(check_command('curl'))
    checks.append(check_command('nvidia-smi'))
    checks.extend(check_nvidia())
    checks.append(check_disk(ROOT, min_free_gb=180))
    checks.append(check_python_module('yaml', required=True))
    # These are expected to be installed by the finetune phase if missing.
    for module in ['torch', 'transformers', 'peft', 'trl', 'datasets', 'accelerate', 'bitsandbytes']:
        checks.append(check_python_module(module, required=False))
    checks.append(check_jobs())
    checks.append(check_ollama_models())
    checks.extend(check_model_names(config))

    checks.append(ok('uv version', command_version('uv', ['--version'])))
    if shutil.which('nvidia-smi'):
        checks.append(ok('nvidia-smi version', command_version('nvidia-smi', ['--version'])))

    print_report(checks)
    write_json(REPORT_JSON, {'checks': checks})
    write_markdown(checks)
    print(f'Wrote {REPORT_JSON}')
    print(f'Wrote {REPORT_MD}')

    failures = [c for c in checks if c['status'] == 'fail']
    if failures:
        print(f'Preflight failed with {len(failures)} failure(s).')
        return 1
    print('Preflight passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
