#!/usr/bin/env python3
from __future__ import annotations
import json, subprocess, re
from pathlib import Path
ROOT=Path('/home/agent/work/discourse-sql-ft')
DB='discourse_sql_ft'
SYSTEM='You translate English questions about a Discourse PostgreSQL database into safe read-only PostgreSQL SQL. Output only SQL. No Markdown. No explanation. Use only the provided schema.'
TABLE_RE=re.compile(r'\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)',re.I)
REPAIRS=[
('suspicious_logins','Show recent suspicious login events.',"SELECT id, user_id, client_ip, user_agent, action, created_at FROM user_auth_token_logs ORDER BY created_at DESC LIMIT 20;"),
('top_referred_topics','Which referred topics have the most incoming links?',"SELECT t.id, t.title, COUNT(*) AS incoming_link_count FROM incoming_links il JOIN posts p ON p.id=il.post_id JOIN topics t ON t.id=p.topic_id WHERE t.deleted_at IS NULL GROUP BY t.id, t.title ORDER BY incoming_link_count DESC, t.id LIMIT 20;"),
('top_traffic_sources','Which external domains send the most traffic?',"SELECT id.name AS domain, COUNT(*) AS incoming_link_count FROM incoming_links il JOIN incoming_referers ir ON ir.id=il.incoming_referer_id JOIN incoming_domains id ON id.id=ir.incoming_domain_id GROUP BY id.name ORDER BY incoming_link_count DESC, id.name LIMIT 20;")
]
def psql(sql): return subprocess.run(['psql','-d',DB,'-qAt','-c',sql],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True).stdout
def schema(tables):
 out=[]
 for t in tables:
  rows=psql(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='public' AND table_name='{t}' ORDER BY ordinal_position").splitlines()
  b=[t+'(']
  for r in rows:
   c,typ=r.split('|',1); b.append(f'  {c} {typ},')
  if len(b)>1: b[-1]=b[-1].rstrip(',')
  b.append(')'); out.append('\n'.join(b))
 return '\n\n'.join(out)
def check(sql):
 inner=sql.rstrip(';')
 wrapper="BEGIN READ ONLY; SET LOCAL statement_timeout='5000ms'; SELECT COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb)::text FROM ("+inner+") q; ROLLBACK;"
 cp=subprocess.run(['psql','-d',DB,'-qAt','-c',wrapper],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=8)
 if cp.returncode: raise RuntimeError(cp.stderr)
rows=[]
for name,q,sql in REPAIRS:
 check(sql)
 ts=sorted(set(TABLE_RE.findall(sql)))
 rows.append({'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':'Schema:\n'+schema(ts)+'\n\nNotes:\n- This example repairs and covers a Discourse core report.\n- Use read-only PostgreSQL SELECT SQL.\n\nQuestion: '+q},{'role':'assistant','content':sql}], 'family':'discourse_core_report', 'source':'Discourse core reports repaired', 'source_name':name, 'coverage_tables':ts})
out=ROOT/'dataset/builtin_queries_reports_repairs.jsonl'
out.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
with (ROOT/'dataset/train.jsonl').open('a') as f:
 for r in rows: f.write(json.dumps(r,ensure_ascii=False)+'\n')
print(json.dumps({'repairs_added':len(rows),'path':str(out)},indent=2))
