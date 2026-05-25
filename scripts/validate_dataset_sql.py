#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path('/home/agent/work/discourse-sql-ft')
DB = 'discourse_sql_ft'
FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|truncate|copy|grant|revoke|call|do|merge|vacuum|analyze)\b", re.I)


def extract_sql(row: dict) -> str:
    if 'sql' in row:
        return row['sql']
    for msg in reversed(row.get('messages', [])):
        if msg.get('role') == 'assistant':
            return msg.get('content', '')
    raise ValueError('row has neither sql nor assistant message')


def safety(sql: str) -> tuple[bool, str]:
    s = sql.strip().rstrip(';').strip()
    if not s:
        return False, 'empty'
    if not re.match(r'^(select|with)\b', s, re.I):
        return False, 'not_select_or_with'
    if FORBIDDEN.search(s):
        return False, 'forbidden_keyword'
    if ';' in s:
        return False, 'multiple_statements'
    return True, 'ok'


def run_sql(sql: str, timeout_s: int) -> tuple[bool, str]:
    ok, reason = safety(sql)
    if not ok:
        return False, reason
    inner = sql.strip().rstrip(';')
    wrapper = (
        "BEGIN READ ONLY; "
        "SET LOCAL statement_timeout='5000ms'; "
        "SELECT COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb)::text FROM (" + inner + ") q; "
        "ROLLBACK;"
    )
    try:
        cp = subprocess.run(['psql', '-d', DB, '-qAt', '-c', wrapper], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return False, 'timeout'
    if cp.returncode != 0:
        return False, (cp.stderr or cp.stdout)[-1200:]
    return True, 'ok'


def main() -> int:
    ap = argparse.ArgumentParser(description='Validate dataset SQL with read-only execution wrappers.')
    ap.add_argument('path', nargs='?', default=str(ROOT / 'dataset/train.jsonl'))
    ap.add_argument('--timeout', type=int, default=8)
    ap.add_argument('--fail-fast', action='store_true')
    args = ap.parse_args()

    path = Path(args.path)
    total = 0
    failures: list[dict] = []
    started = time.time()
    with path.open() as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            total += 1
            try:
                row = json.loads(line)
                sql = extract_sql(row)
                ok, err = run_sql(sql, args.timeout)
            except Exception as e:
                ok, err = False, f'{type(e).__name__}: {e}'
            if not ok:
                rec = {'line': line_no, 'error': err}
                failures.append(rec)
                print(json.dumps(rec), file=sys.stderr, flush=True)
                if args.fail_fast:
                    break
            if total % 100 == 0:
                print(f'validated {total} rows; failures={len(failures)}', flush=True)

    summary = {'path': str(path), 'total': total, 'failures': len(failures), 'elapsed_s': round(time.time() - started, 2)}
    print(json.dumps(summary, indent=2), flush=True)
    if failures:
        print('VALIDATION_FAILED', file=sys.stderr)
        return 1
    print('VALIDATION_OK', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
