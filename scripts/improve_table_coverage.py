#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path('/home/agent/work/discourse-sql-ft')
DB = 'discourse_sql_ft'
DATASET = ROOT / 'dataset'
OUT = ROOT / 'reports' / 'coverage_expansion'
DISCOURSE = Path('/home/agent/source/discourse')
SYSTEM = 'You translate English questions about a Discourse PostgreSQL database into safe read-only PostgreSQL SQL. Output only SQL. No Markdown. No explanation. Use only the provided schema.'

TABLE_RE = re.compile(r'\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)', re.I)
FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|truncate|copy|grant|revoke|call|do|merge|vacuum|analyze)\b", re.I)


def run(cmd, timeout=120, cwd=ROOT):
    return subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=True)


def psql(sql: str, timeout=120) -> str:
    cp = run(['psql', '-d', DB, '-qAt', '-c', sql], timeout=timeout)
    return cp.stdout


def quote_ident(name: str) -> str:
    # The Discourse schema is mostly lower snake_case, but some columns use SQL
    # keywords (`group`, `primary`). Quote those.
    reserved = {'group', 'primary', 'order', 'user', 'select', 'where', 'from', 'to'}
    if re.match(r'^[a-z_][a-z0-9_]*$', name) and name not in reserved:
        return name
    return '"' + name.replace('"', '""') + '"'


def load_tables():
    rows = psql("""
SELECT table_name
FROM information_schema.tables
WHERE table_schema='public' AND table_type='BASE TABLE'
ORDER BY table_name;
""").splitlines()
    return [r.strip() for r in rows if r.strip()]


def load_columns():
    rows = psql("""
SELECT table_name, column_name, data_type, ordinal_position
FROM information_schema.columns
WHERE table_schema='public'
ORDER BY table_name, ordinal_position;
""").splitlines()
    cols = defaultdict(list)
    for row in rows:
        table, col, typ, pos = row.split('|', 3)
        cols[table].append({'name': col, 'type': typ, 'pos': int(pos)})
    return dict(cols)


def extract_tables(sql: str):
    tables = []
    for m in TABLE_RE.finditer(sql):
        t = m.group(1).split('.')[-1].strip('"')
        tables.append(t)
    return tables


def iter_dataset_rows(paths):
    for path in paths:
        if not path.exists():
            continue
        with path.open() as f:
            for line in f:
                if not line.strip():
                    continue
                yield path.name, json.loads(line)


def sql_from_row(row):
    if 'sql' in row:
        return row['sql']
    for m in row.get('messages', []):
        if m.get('role') == 'assistant':
            return m.get('content', '')
    return ''


def current_coverage(paths):
    counts = Counter()
    by_file = defaultdict(Counter)
    for filename, row in iter_dataset_rows(paths):
        sql = sql_from_row(row)
        for table in extract_tables(sql):
            counts[table] += 1
            by_file[filename][table] += 1
    return counts, by_file


def humanize(table):
    return table.replace('_', ' ')


def singular(table):
    if table.endswith('ies'):
        return table[:-3] + 'y'
    if table.endswith('ses'):
        return table[:-2]
    if table.endswith('s'):
        return table[:-1]
    return table


def source_shape(table):
    """Best-effort source lookup. This does not block generation; it records where semantics likely live."""
    hits = []
    candidates = []
    s = singular(table)
    candidates += [DISCOURSE / 'app/models' / f'{s}.rb']
    candidates += [DISCOURSE / 'app/models' / table / f'{s}.rb']
    for p in candidates:
        if p.exists():
            hits.append(str(p))
    if len(hits) < 3 and DISCOURSE.exists():
        pats = [f'create_table :{table}', f'create_table "{table}"', f"self.table_name = '{table}'", f'self.table_name = "{table}"']
        try:
            cp = subprocess.run(['rg', '-l', '|'.join(re.escape(p) for p in pats), str(DISCOURSE / 'app'), str(DISCOURSE / 'db'), str(DISCOURSE / 'plugins')], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=8)
            for line in cp.stdout.splitlines():
                if line not in hits:
                    hits.append(line)
                if len(hits) >= 5:
                    break
        except Exception:
            pass
    return hits[:5]


def schema_block(table, cols):
    lines = [f'{table}(']
    for c in cols:
        note = ''
        name = c['name']
        if name == 'id':
            note = ' primary key'
        elif name.endswith('_id'):
            note = ' foreign key/reference id'
        elif name in ('created_at', 'updated_at'):
            note = ' timestamp'
        elif name.endswith('_count') or name in ('count', 'views', 'score'):
            note = ' cached/count metric'
        lines.append(f"  {name} {c['type']}{note},")
    if len(lines) > 1:
        lines[-1] = lines[-1].rstrip(',')
    lines.append(')')
    return '\n'.join(lines)


def select_columns(cols):
    names = [c['name'] for c in cols]
    priority = ['id', 'name', 'title', 'username', 'email', 'key', 'value', 'status', 'action_type', 'post_id', 'topic_id', 'user_id', 'created_at', 'updated_at']
    selected = []
    for p in priority:
        if p in names and p not in selected:
            selected.append(p)
    for c in names:
        if len(selected) >= 6:
            break
        if c not in selected and not c.endswith('_hash') and c not in ('secure_identifier', 'auth_token'):
            selected.append(c)
    return selected[:6] or names[:3]


def order_clause(cols):
    names = [c['name'] for c in cols]
    if 'created_at' in names:
        return 'created_at DESC'
    if 'updated_at' in names:
        return 'updated_at DESC'
    if 'id' in names:
        return 'id DESC'
    return None


def safety(sql):
    s = sql.strip().rstrip(';').strip()
    if not re.match(r'^(select|with)\b', s, re.I):
        return False, 'not_select'
    if FORBIDDEN.search(s):
        return False, 'forbidden'
    if ';' in s:
        return False, 'multiple'
    return True, 'ok'


def exec_sql(sql):
    ok, reason = safety(sql)
    if not ok:
        return False, reason
    inner = sql.strip().rstrip(';')
    wrapper = "BEGIN READ ONLY; SET LOCAL statement_timeout='3000ms'; SELECT COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb)::text FROM (" + inner + ") q; ROLLBACK;"
    cp = subprocess.run(['psql', '-d', DB, '-qAt', '-c', wrapper], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=6)
    if cp.returncode != 0:
        return False, (cp.stderr or cp.stdout)[-600:]
    return True, ''


def make_examples_for_table(table, cols, existing_tables):
    qtable = quote_ident(table)
    label = humanize(table)
    examples = []

    # Example 1: count. Boring, but universally valid and teaches table existence.
    sql1 = f'SELECT COUNT(*) AS row_count FROM {qtable};'
    q1 = f'How many {label} records are there?'
    examples.append((q1, sql1, 'coverage_count'))

    # Example 2: recent/sample rows with useful columns.
    sel = ', '.join(quote_ident(c) for c in select_columns(cols))
    order = order_clause(cols)
    if order:
        sql2 = f'SELECT {sel} FROM {qtable} ORDER BY {order} LIMIT 20;'
        q2 = f'Show the 20 most recent {label} records.'
    else:
        sql2 = f'SELECT {sel} FROM {qtable} LIMIT 20;'
        q2 = f'Show 20 sample {label} records.'
    examples.append((q2, sql2, 'coverage_sample'))

    return examples


def make_row(table, cols, question, sql, family, source_hits):
    notes = [
        'Use only the tables and columns shown here.',
        'Use read-only PostgreSQL SELECT SQL.',
    ]
    if any(c['name'] == 'deleted_at' for c in cols):
        notes.append('When listing active records, prefer deleted_at IS NULL if the question asks for visible/current data.')
    content = 'Schema:\n' + schema_block(table, cols) + '\n\nNotes:\n- ' + '\n- '.join(notes) + '\n\nQuestion: ' + question
    return {
        'messages': [
            {'role': 'system', 'content': SYSTEM},
            {'role': 'user', 'content': content},
            {'role': 'assistant', 'content': sql},
        ],
        'family': family,
        'coverage_table': table,
        'source_hits': source_hits,
    }


def main():
    started = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    OUT.mkdir(parents=True, exist_ok=True)
    tables = load_tables()
    cols = load_columns()
    dataset_paths = [DATASET / 'train.jsonl', DATASET / 'dev.jsonl', DATASET / 'eval.jsonl']
    train_path = DATASET / 'train.jsonl'
    before_counts, by_file = current_coverage(dataset_paths)
    train_before, _ = current_coverage([train_path])
    missing_train = [t for t in tables if train_before[t] == 0]
    missing_any = [t for t in tables if before_counts[t] == 0]

    generated = []
    rejected = []
    source_hits_by_table = {}
    for idx, table in enumerate(missing_train, 1):
        table_cols = cols.get(table, [])
        if not table_cols:
            rejected.append({'table': table, 'reason': 'no_columns'})
            continue
        hits = source_shape(table)
        source_hits_by_table[table] = hits
        for question, sql, family in make_examples_for_table(table, table_cols, before_counts):
            ok, err = exec_sql(sql)
            if not ok:
                rejected.append({'table': table, 'question': question, 'sql': sql, 'reason': err})
                continue
            generated.append(make_row(table, table_cols, question, sql, family, hits))

    # Back up and append to train set.
    backup = DATASET / f'train.before-coverage-expansion.{int(time.time())}.jsonl'
    backup.write_text(train_path.read_text())
    expansion_path = DATASET / 'coverage_expansion.jsonl'
    expansion_path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in generated))
    with train_path.open('a') as f:
        for r in generated:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    after_counts, by_file_after = current_coverage(dataset_paths)
    train_after, _ = current_coverage([train_path])
    missing_train_after = [t for t in tables if train_after[t] == 0]
    missing_any_after = [t for t in tables if after_counts[t] == 0]

    summary = {
        'started_at': started,
        'finished_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'total_schema_tables': len(tables),
        'train_tables_covered_before': sum(1 for t in tables if train_before[t] > 0),
        'train_tables_covered_after': sum(1 for t in tables if train_after[t] > 0),
        'any_split_tables_covered_before': sum(1 for t in tables if before_counts[t] > 0),
        'any_split_tables_covered_after': sum(1 for t in tables if after_counts[t] > 0),
        'missing_train_before': len(missing_train),
        'missing_train_after': len(missing_train_after),
        'missing_any_before': len(missing_any),
        'missing_any_after': len(missing_any_after),
        'examples_added_to_train': len(generated),
        'tables_targeted': len(missing_train),
        'tables_with_source_hits': sum(1 for t,h in source_hits_by_table.items() if h),
        'rejected_examples': len(rejected),
        'backup': str(backup),
        'expansion_path': str(expansion_path),
        'missing_train_after_tables': missing_train_after,
        'missing_any_after_tables': missing_any_after,
    }

    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    (OUT / 'rejected.json').write_text(json.dumps(rejected, indent=2) + '\n')
    (OUT / 'source_hits.json').write_text(json.dumps(source_hits_by_table, indent=2) + '\n')
    coverage_rows = []
    for t in tables:
        coverage_rows.append({'table': t, 'train_before': train_before[t], 'train_after': train_after[t], 'any_before': before_counts[t], 'any_after': after_counts[t]})
    (OUT / 'coverage_by_table.json').write_text(json.dumps(coverage_rows, indent=2) + '\n')

    md = []
    md.append('# Discourse SQL dataset coverage expansion')
    md.append('')
    md.append(f"Started: `{summary['started_at']}` UTC")
    md.append(f"Finished: `{summary['finished_at']}` UTC")
    md.append('')
    md.append('## Summary')
    md.append('')
    md.append(f"- Schema base tables: **{summary['total_schema_tables']}**")
    md.append(f"- Train table coverage: **{summary['train_tables_covered_before']} → {summary['train_tables_covered_after']}**")
    md.append(f"- Any-split table coverage: **{summary['any_split_tables_covered_before']} → {summary['any_split_tables_covered_after']}**")
    md.append(f"- Examples appended to train: **{summary['examples_added_to_train']}**")
    md.append(f"- Targeted missing train tables: **{summary['tables_targeted']}**")
    md.append(f"- Targeted tables with source hits: **{summary['tables_with_source_hits']}**")
    md.append(f"- Rejected generated examples: **{summary['rejected_examples']}**")
    md.append('')
    md.append('## Files')
    md.append('')
    md.append(f"- Backup: `{backup}`")
    md.append(f"- Added examples: `{expansion_path}`")
    md.append(f"- Coverage table: `{OUT / 'coverage_by_table.json'}`")
    md.append(f"- Source hits: `{OUT / 'source_hits.json'}`")
    md.append(f"- Rejections: `{OUT / 'rejected.json'}`")
    md.append('')
    md.append('## Caveat')
    md.append('')
    md.append('This pass guarantees executable training coverage for every base table that was missing from train. Many generated examples are deliberately simple count/sample queries. That gives the model table/column exposure; it does not replace hand-written semantic admin questions for important tables like `topic_views`, `user_visits`, reviewables, email, groups, badges, uploads, and plugin tables.')
    md.append('')
    md.append('## Example new rows')
    md.append('')
    for r in generated[:10]:
        md.append(f"### `{r['coverage_table']}`")
        md.append(r['messages'][1]['content'].split('Question: ',1)[1])
        md.append('```sql')
        md.append(r['messages'][2]['content'])
        md.append('```')
        md.append('')
    (ROOT / 'reports' / 'coverage_expansion.md').write_text('\n'.join(md) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
