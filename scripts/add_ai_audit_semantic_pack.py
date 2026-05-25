#!/usr/bin/env python3
from __future__ import annotations
import json, subprocess, re
from pathlib import Path
ROOT=Path('/home/agent/work/discourse-sql-ft')
DB='discourse_sql_ft'
SYSTEM='You translate English questions about a Discourse PostgreSQL database into safe read-only PostgreSQL SQL. Output only SQL. No Markdown. No explanation. Use only the provided schema.'
TABLE_RE=re.compile(r'\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)',re.I)
EXAMPLES=[
('ai_api_audit_logs','Which AI features made the most API requests in the last 30 days?',"SELECT a.feature_name, COUNT(*) AS request_count FROM ai_api_audit_logs a WHERE a.created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY a.feature_name ORDER BY request_count DESC, a.feature_name LIMIT 20;"),
('ai_api_audit_logs','Which language models used the most AI tokens in the last 30 days?',"SELECT a.language_model, SUM(a.request_tokens) AS prompt_tokens, SUM(a.response_tokens) AS completion_tokens, SUM(a.cache_read_tokens) AS cache_read_tokens, SUM(a.cache_write_tokens) AS cache_write_tokens, COUNT(*) AS request_count FROM ai_api_audit_logs a WHERE a.created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY a.language_model ORDER BY (SUM(a.request_tokens) + SUM(a.response_tokens)) DESC NULLS LAST, a.language_model LIMIT 20;"),
('ai_api_audit_logs','Which users consumed the most AI tokens in the last 30 days?',"SELECT u.username, COUNT(*) AS ai_requests, SUM(a.request_tokens + a.response_tokens) AS total_tokens FROM ai_api_audit_logs a JOIN users u ON u.id=a.user_id WHERE a.created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY u.username ORDER BY total_tokens DESC NULLS LAST, u.username LIMIT 20;"),
('ai_api_audit_logs','Show recent failed AI API requests.',"SELECT a.id, u.username, a.feature_name, a.language_model, a.response_status, a.duration_msecs, a.created_at FROM ai_api_audit_logs a LEFT JOIN users u ON u.id=a.user_id WHERE a.response_status IS NOT NULL AND a.response_status >= 400 ORDER BY a.created_at DESC LIMIT 20;"),
('ai_api_audit_logs','Which AI features have the slowest average response time?',"SELECT a.feature_name, AVG(a.duration_msecs) AS avg_duration_msecs, COUNT(*) AS request_count FROM ai_api_audit_logs a WHERE a.created_at >= CURRENT_DATE - INTERVAL '30 days' AND a.duration_msecs IS NOT NULL GROUP BY a.feature_name HAVING COUNT(*) >= 5 ORDER BY avg_duration_msecs DESC, a.feature_name LIMIT 20;"),
('ai_api_audit_logs','Which topics generated the most AI API calls?',"SELECT t.id, t.title, COUNT(*) AS ai_request_count FROM ai_api_audit_logs a JOIN topics t ON t.id=a.topic_id WHERE a.created_at >= CURRENT_DATE - INTERVAL '30 days' AND t.deleted_at IS NULL GROUP BY t.id, t.title ORDER BY ai_request_count DESC, t.id LIMIT 20;"),
('ai_api_request_stats','Show daily AI usage by feature for the last 30 days.',"SELECT ars.bucket_date::date AS day, ars.feature_name, SUM(ars.usage_count) AS usage_count, SUM(ars.request_tokens) AS request_tokens, SUM(ars.response_tokens) AS response_tokens FROM ai_api_request_stats ars WHERE ars.bucket_date >= CURRENT_DATE - INTERVAL '30 days' GROUP BY ars.bucket_date::date, ars.feature_name ORDER BY day DESC, usage_count DESC, ars.feature_name LIMIT 100;"),
('ai_api_request_stats','Which users have the highest rolled-up AI usage this month?',"SELECT u.username, SUM(ars.usage_count) AS usage_count, SUM(ars.request_tokens + ars.response_tokens) AS total_tokens FROM ai_api_request_stats ars JOIN users u ON u.id=ars.user_id WHERE ars.bucket_date >= date_trunc('month', CURRENT_DATE) GROUP BY u.username ORDER BY total_tokens DESC NULLS LAST, u.username LIMIT 20;"),
]

def psql(sql):
 return subprocess.run(['psql','-d',DB,'-qAt','-c',sql],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True).stdout

def table_schema(table):
 rows=psql(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='public' AND table_name='{table}' ORDER BY ordinal_position").splitlines()
 out=[table+'(']
 for r in rows:
  c,t=r.split('|',1); out.append(f'  {c} {t},')
 if len(out)>1: out[-1]=out[-1].rstrip(',')
 out.append(')')
 return '\n'.join(out)

def tables(sql):
 return sorted(set(m.group(1) for m in TABLE_RE.finditer(sql)))

def check(sql):
 inner=sql.rstrip(';')
 wrapper="BEGIN READ ONLY; SET LOCAL statement_timeout='3000ms'; SELECT COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb)::text FROM ("+inner+") q; ROLLBACK;"
 cp=subprocess.run(['psql','-d',DB,'-qAt','-c',wrapper],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=6)
 if cp.returncode: raise RuntimeError(cp.stderr)
rows=[]
for family,q,sql in EXAMPLES:
 check(sql)
 ts=tables(sql)
 schema='\n\n'.join(table_schema(t) for t in ts)
 rows.append({'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':'Schema:\n'+schema+'\n\nNotes:\n- Use read-only PostgreSQL SELECT SQL.\n- ai_api_audit_logs contains individual AI API calls.\n- ai_api_request_stats contains rolled-up AI usage buckets.\n- For token usage, sum request_tokens and response_tokens; cache_read_tokens and cache_write_tokens are separate cache metrics.\n\nQuestion: '+q},{'role':'assistant','content':sql}], 'family':'semantic_ai_api_audit', 'coverage_tables':ts})
out=ROOT/'dataset/semantic_ai_audit_pack.jsonl'
out.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
with (ROOT/'dataset/train.jsonl').open('a') as f:
 for r in rows: f.write(json.dumps(r,ensure_ascii=False)+'\n')
print(json.dumps({'semantic_ai_audit_examples_added':len(rows),'path':str(out)},indent=2))
