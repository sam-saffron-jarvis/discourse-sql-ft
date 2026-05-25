#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path

ROOT = Path('/home/agent/work/discourse-sql-ft')
DB = 'discourse_sql_ft'
BASE_MODEL = 'Qwen/Qwen3.5-9B'
ADAPTER = ROOT / 'training/qwen35-9b-lora/adapter'
SCHEMA = (ROOT / 'config/schema.txt').read_text()
SYSTEM = 'You translate English questions about a Discourse PostgreSQL database into safe read-only PostgreSQL SQL. Output only SQL. No Markdown. No explanation. Use only the provided schema.'
FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|truncate|copy|grant|revoke|call|do|merge|vacuum|analyze)\b", re.I)


def load_eval(limit: int | None):
    rows = []
    with (ROOT / 'dataset/eval.jsonl').open() as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows[:limit] if limit else rows


def extract_sql(text: str) -> str:
    text = text.strip()
    # Qwen thinking-mode models may emit analysis despite the instruction.  Keep
    # only content after the final </think> marker if present.
    if '</think>' in text:
        text = text.rsplit('</think>', 1)[1].strip()
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    if m:
        text = m.group(1).strip()
    # If prose still leaked, grab the first SELECT/WITH-looking statement.
    m = re.search(r"\b(with|select)\b.*", text, re.S | re.I)
    if m:
        text = m.group(0).strip()
    text = re.sub(r"^\s*(Here is|Here's|The SQL is)[:\s]*", "", text, flags=re.I)
    # keep first statement only if the model appends prose after semicolon
    if ';' in text:
        text = text.split(';', 1)[0].strip() + ';'
    return text.strip()


def safety(sql: str) -> tuple[bool, str]:
    s = sql.strip().rstrip(';').strip()
    if not s:
        return False, 'empty'
    if not re.match(r'^(select|with)\b', s, re.I):
        return False, 'not_select_or_with'
    if FORBIDDEN.search(s):
        return False, 'forbidden_keyword'
    # multiple statements, allowing trailing semicolon only
    if ';' in s:
        return False, 'multiple_statements'
    return True, 'ok'


def run_sql(sql: str) -> tuple[bool, object, str]:
    ok, reason = safety(sql)
    if not ok:
        return False, None, reason
    inner = sql.strip().rstrip(';')
    wrapper = "BEGIN READ ONLY; SET LOCAL statement_timeout='3000ms'; SELECT COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb)::text FROM (" + inner + ") q; ROLLBACK;"
    try:
        cp = subprocess.run(['psql', '-d', DB, '-qAt', '-c', wrapper], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
    except subprocess.TimeoutExpired:
        return False, None, 'timeout'
    if cp.returncode != 0:
        return False, None, (cp.stderr or cp.stdout)[-1000:]
    lines = [l for l in cp.stdout.splitlines() if l.strip() and l.strip() not in ('BEGIN', 'SET', 'ROLLBACK')]
    if not lines:
        return False, None, 'no_result'
    try:
        return True, json.loads(lines[0]), ''
    except Exception as e:
        return False, None, f'json_parse:{e}:{lines[:3]}'


def normalize_result(x):
    # jsonb object key order is stable enough after parsing; preserve row order.
    return x


def result_match(a, b) -> bool:
    return normalize_result(a) == normalize_result(b)


def generate_all(model_label: str, adapter: bool, rows, out_dir: Path):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    if adapter:
        from peft import PeftModel

    out_dir.mkdir(parents=True, exist_ok=True)
    details_path = out_dir / 'details.jsonl'
    summary_path = out_dir / 'summary.json'

    tokenizer = AutoTokenizer.from_pretrained(str(ADAPTER) if adapter else BASE_MODEL, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4', bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
    model = AutoModelForCausalLM.from_pretrained(BASE_MODEL, quantization_config=bnb, device_map='auto', trust_remote_code=True, torch_dtype=torch.bfloat16)
    if adapter:
        model = PeftModel.from_pretrained(model, str(ADAPTER))
    model.eval()

    completed = []
    if details_path.exists():
        with details_path.open() as existing:
            for line in existing:
                if line.strip():
                    completed.append(json.loads(line))
    start_idx = len(completed) + 1
    stats = {'model': model_label, 'total': len(rows), 'safe': sum(1 for r in completed if r.get('safe_ok')), 'exec_ok': sum(1 for r in completed if r.get('pred_ok')), 'exact': sum(1 for r in completed if r.get('exact')), 'started_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    mode = 'a' if completed else 'w'
    with details_path.open(mode) as f:
        for i, row in enumerate(rows[start_idx-1:], start_idx):
            q = row['question']
            canonical_sql = row['sql']
            can_ok, can_result, can_err = run_sql(canonical_sql)
            messages = [
                {'role': 'system', 'content': SYSTEM},
                {'role': 'user', 'content': 'Schema:\n' + SCHEMA + '\n\nQuestion: ' + q},
            ]
            prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
            inputs = tokenizer([prompt], return_tensors='pt').to(model.device)
            with torch.no_grad():
                gen = model.generate(**inputs, max_new_tokens=192, do_sample=False, temperature=None, top_p=None, pad_token_id=tokenizer.pad_token_id, eos_token_id=tokenizer.eos_token_id)
            output = tokenizer.decode(gen[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)
            pred_sql = extract_sql(output)
            safe_ok, safe_reason = safety(pred_sql)
            pred_ok, pred_result, pred_err = run_sql(pred_sql)
            exact = bool(can_ok and pred_ok and result_match(can_result, pred_result))
            if safe_ok: stats['safe'] += 1
            if pred_ok: stats['exec_ok'] += 1
            if exact: stats['exact'] += 1
            rec = {
                'idx': i, 'family': row.get('family'), 'question': q,
                'canonical_sql': canonical_sql, 'pred_sql': pred_sql, 'raw_output': output,
                'canonical_ok': can_ok, 'canonical_error': can_err,
                'safe_ok': safe_ok, 'safe_reason': safe_reason,
                'pred_ok': pred_ok, 'pred_error': pred_err,
                'exact': exact,
            }
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            f.flush()
            if i % 10 == 0 or i == len(rows):
                stats['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                summary_path.write_text(json.dumps(stats, indent=2) + '\n')
                print(f"{model_label}: {i}/{len(rows)} exact={stats['exact']} exec={stats['exec_ok']} safe={stats['safe']}", flush=True)
    stats['finished_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    summary_path.write_text(json.dumps(stats, indent=2) + '\n')
    del model
    torch.cuda.empty_cache()
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=200)
    ap.add_argument('--only', choices=['base', 'tuned', 'both'], default='both')
    args = ap.parse_args()
    rows = load_eval(args.limit)
    out_root = ROOT / 'eval' / 'execution'
    out_root.mkdir(parents=True, exist_ok=True)
    summaries = {}
    if args.only in ('base', 'both'):
        summaries['base'] = generate_all('base', False, rows, out_root / 'base')
    if args.only in ('tuned', 'both'):
        summaries['tuned'] = generate_all('tuned', True, rows, out_root / 'tuned')
    comp = {'limit': len(rows), 'summaries': summaries}
    if 'base' in summaries and 'tuned' in summaries:
        b, t = summaries['base'], summaries['tuned']
        comp['delta_exact'] = t['exact'] - b['exact']
        comp['base_exact_rate'] = b['exact'] / b['total'] if b['total'] else 0
        comp['tuned_exact_rate'] = t['exact'] / t['total'] if t['total'] else 0
    (out_root / 'comparison.json').write_text(json.dumps(comp, indent=2) + '\n')
    (ROOT / 'reports' / 'execution_eval.md').write_text('# Execution Eval\n\n```json\n' + json.dumps(comp, indent=2) + '\n```\n')
    print(json.dumps(comp, indent=2))

if __name__ == '__main__':
    main()
