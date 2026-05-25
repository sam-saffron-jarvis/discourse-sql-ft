#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import sqlparse

ROOT = Path(__file__).resolve().parents[1]


def prettify_sql(sql: str) -> str:
    sql = sql.strip()
    if not sql:
        return sql
    formatted = sqlparse.format(
        sql,
        keyword_case="upper",
        identifier_case=None,
        reindent_aligned=True,
        indent_width=2,
        wrap_after=88,
        strip_comments=False,
        use_space_around_operators=True,
    ).strip()
    # sqlparse can leave excessive blank lines around CTEs/comments; keep it tidy.
    lines = []
    blank = False
    for line in formatted.splitlines():
        if line.strip():
            lines.append(line.rstrip())
            blank = False
        elif not blank:
            lines.append("")
            blank = True
    formatted = "\n".join(lines).strip()
    if sql.endswith(";") and not formatted.endswith(";"):
        formatted += ";"
    return formatted


def update_jsonl(path: Path, dry_run: bool = False) -> tuple[int, int]:
    changed = 0
    total = 0
    out = []
    for line in path.read_text().splitlines():
        if not line.strip():
            out.append(line)
            continue
        row = json.loads(line)
        total += 1
        if "messages" in row:
            for msg in row["messages"]:
                if msg.get("role") == "assistant" and isinstance(msg.get("content"), str):
                    old = msg["content"]
                    new = prettify_sql(old)
                    if new != old:
                        msg["content"] = new
                        changed += 1
        elif "sql" in row and isinstance(row.get("sql"), str):
            old = row["sql"]
            new = prettify_sql(old)
            if new != old:
                row["sql"] = new
                changed += 1
        out.append(json.dumps(row, ensure_ascii=False))
    if changed and not dry_run:
        path.write_text("\n".join(out) + "\n")
    return total, changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", default=["dataset/train.jsonl"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    for p in args.paths:
        path = ROOT / p
        total, changed = update_jsonl(path, dry_run=args.dry_run)
        print(f"{p}: rows={total} changed_sql={changed}")


if __name__ == "__main__":
    main()
