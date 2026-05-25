#!/usr/bin/env python3
from __future__ import annotations
import json, subprocess, re
from pathlib import Path
ROOT=Path('/home/agent/work/discourse-sql-ft'); DB='discourse_sql_ft'
SYSTEM='You translate English questions about a Discourse PostgreSQL database into safe read-only PostgreSQL SQL. Output only SQL. No Markdown. No explanation. Use only the provided schema.'
SQL="SELECT p.id AS post_id, t.title, SUM(CASE WHEN pvv.direction = 'up' THEN 1 WHEN pvv.direction = 'down' THEN -1 ELSE 0 END) AS vote_score FROM post_voting_votes pvv JOIN posts p ON p.id=pvv.votable_id AND pvv.votable_type='Post' JOIN topics t ON t.id=p.topic_id WHERE p.deleted_at IS NULL AND t.deleted_at IS NULL GROUP BY p.id, t.title ORDER BY vote_score DESC NULLS LAST, p.id LIMIT 20;"
Q='Which posts have the highest post-voting score?'
TABLE_RE=re.compile(r'\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)',re.I)
def psql(sql): return subprocess.run(['psql','-d',DB,'-qAt','-c',sql],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True).stdout
def check(sql):
 inner=sql.rstrip(';'); wrapper="BEGIN READ ONLY; SET LOCAL statement_timeout='5000ms'; SELECT COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb)::text FROM ("+inner+") q; ROLLBACK;"
 cp=subprocess.run(['psql','-d',DB,'-qAt','-c',wrapper],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=8)
 if cp.returncode: raise RuntimeError(cp.stderr)
def schema(ts):
 out=[]
 for t in ts:
  rows=psql(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='public' AND table_name='{t}' ORDER BY ordinal_position").splitlines(); b=[t+'(']
  for r in rows:
   c,typ=r.split('|',1); b.append(f'  {c} {typ},')
  b[-1]=b[-1].rstrip(','); b.append(')'); out.append('\n'.join(b))
 return '\n\n'.join(out)
check(SQL); ts=sorted(set(TABLE_RE.findall(SQL)))
r={'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':'Schema:\n'+schema(ts)+'\n\nNotes:\n- This example repairs a source-mined Discourse post voting query.\n- post_voting_votes.direction is text; treat up votes as +1 and down votes as -1.\n- Use read-only PostgreSQL SELECT SQL.\n\nQuestion: '+Q},{'role':'assistant','content':SQL}], 'family':'source_mined_post_voting', 'source':'Discourse source mined SQL concepts repaired', 'source_name':'post_voting', 'coverage_tables':ts}
out=ROOT/'dataset/source_mined_semantic_repairs.jsonl'; out.write_text(json.dumps(r,ensure_ascii=False)+'\n')
with (ROOT/'dataset/train.jsonl').open('a') as f: f.write(json.dumps(r,ensure_ascii=False)+'\n')
print(json.dumps({'repairs_added':1,'path':str(out)},indent=2))
