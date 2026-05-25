from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path('/home/agent/work/discourse-sql-ft')
CONFIG_PATH = ROOT / 'config' / 'experiment.yaml'


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open('r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def ensure_dirs(*paths: Path) -> None:
    for p in paths:
        p.mkdir(parents=True, exist_ok=True)


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
        f.write('\n')
    os.replace(tmp, path)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def run(cmd: list[str], *, timeout: int = 30, cwd: Path | None = None, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd or ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=check,
    )


def which(name: str) -> str | None:
    return shutil.which(name)


def ok(item: str, detail: str = '') -> dict[str, str]:
    return {'status': 'ok', 'item': item, 'detail': detail}


def warn(item: str, detail: str) -> dict[str, str]:
    return {'status': 'warn', 'item': item, 'detail': detail}


def fail(item: str, detail: str) -> dict[str, str]:
    return {'status': 'fail', 'item': item, 'detail': detail}


def print_report(checks: list[dict[str, str]]) -> None:
    for c in checks:
        marker = {'ok': 'OK', 'warn': 'WARN', 'fail': 'FAIL'}.get(c['status'], c['status'].upper())
        detail = f" — {c['detail']}" if c.get('detail') else ''
        print(f"[{marker}] {c['item']}{detail}")


def has_failures(checks: list[dict[str, str]]) -> bool:
    return any(c.get('status') == 'fail' for c in checks)
