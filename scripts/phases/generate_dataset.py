#!/usr/bin/env python3
from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from common import ROOT, load_config, write_json

DB='discourse_sql_ft'
SCHEMA=(ROOT/'config/schema.txt').read_text()
OUT=ROOT/'dataset'
REPORT=ROOT/'reports/generate_dataset.md'
random.seed(20260524)

SYSTEM='You translate English questions about a Discourse PostgreSQL database into safe read-only PostgreSQL SQL. Output only SQL. No Markdown. No explanation. Use only the provided schema.'

def psql(sql:str)->list[str]:
    cp=subprocess.run(['psql','-d',DB,'-Atc',sql], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    if cp.returncode!=0:
        raise RuntimeError(cp.stderr+cp.stdout)
    return [l for l in cp.stdout.splitlines() if l]

def vals(sql, fallback):
    try:
        v=psql(sql)
        return v or fallback
    except Exception:
        return fallback

categories=vals("SELECT name FROM categories WHERE read_restricted=false ORDER BY random() LIMIT 30", ['Support','Bug','Dev'])
tags=vals("SELECT name FROM tags ORDER BY random() LIMIT 40", ['login','email','performance'])
users=vals("SELECT username FROM users WHERE id > 0 ORDER BY random() LIMIT 80", ['user_0001'])
reactions=vals("SELECT DISTINCT reaction_value FROM discourse_reactions_reactions ORDER BY reaction_value LIMIT 20", ['clap','laughing','tada'])
chat_channels=vals("SELECT COALESCE(name, 'dm-' || id::text) FROM chat_channels ORDER BY random() LIMIT 30", ['general'])
words=['login','upload','notification','postgres','redis','mobile','email','plugin','theme','search','backup','moderation','performance']

def ex(question, sql, family):
    return {'family':family,'question':question,'sql':sql.strip()+';'}

examples=[]
limits=[5,10,20]
days=[1,7,14,30,60,90,180]

for d in days:
  for lim in limits:
    examples += [
      ex(f"Which {lim} users wrote the most posts in the last {d} days?", f"SELECT u.username, COUNT(*) AS post_count FROM posts p JOIN users u ON u.id=p.user_id WHERE p.created_at >= CURRENT_DATE - INTERVAL '{d} days' AND p.deleted_at IS NULL GROUP BY u.username ORDER BY post_count DESC, u.username LIMIT {lim}", 'top_posters'),
      ex(f"Which {lim} topics have the most likes in the last {d} days?", f"SELECT t.id, t.title, COUNT(pa.id) AS like_count FROM topics t JOIN posts p ON p.topic_id=t.id JOIN post_actions pa ON pa.post_id=p.id AND pa.post_action_type_id=2 WHERE pa.created_at >= CURRENT_DATE - INTERVAL '{d} days' GROUP BY t.id, t.title ORDER BY like_count DESC, t.id LIMIT {lim}", 'top_liked_topics'),
      ex(f"Show the {lim} most active chat channels in the last {d} days.", f"SELECT COALESCE(cc.name, 'DM ' || cc.id::text) AS channel, COUNT(cm.id) AS message_count FROM chat_channels cc JOIN chat_messages cm ON cm.chat_channel_id=cc.id WHERE cm.created_at >= CURRENT_DATE - INTERVAL '{d} days' GROUP BY cc.id, cc.name ORDER BY message_count DESC, channel LIMIT {lim}", 'chat_activity'),
    ]

for c in categories:
  q=c.replace("'","''")
  examples += [
    ex(f"How many visible topics are in the {c} category?", f"SELECT COUNT(*) AS topic_count FROM topics t JOIN categories c ON c.id=t.category_id WHERE c.name = '{q}' AND t.deleted_at IS NULL AND t.visible = true", 'category_counts'),
    ex(f"Which users started the most topics in {c}?", f"SELECT u.username, COUNT(*) AS topic_count FROM topics t JOIN users u ON u.id=t.user_id JOIN categories c ON c.id=t.category_id WHERE c.name = '{q}' AND t.deleted_at IS NULL GROUP BY u.username ORDER BY topic_count DESC, u.username LIMIT 10", 'category_users'),
    ex(f"What is the average number of posts per topic in {c}?", f"SELECT AVG(t.posts_count)::numeric(10,2) AS avg_posts FROM topics t JOIN categories c ON c.id=t.category_id WHERE c.name = '{q}' AND t.deleted_at IS NULL", 'category_avg'),
  ]

for tag in tags:
  q=tag.replace("'","''")
  examples += [
    ex(f"How many topics are tagged {tag}?", f"SELECT COUNT(DISTINCT t.id) AS topic_count FROM topics t JOIN topic_tags tt ON tt.topic_id=t.id JOIN tags tg ON tg.id=tt.tag_id WHERE tg.name = '{q}' AND t.deleted_at IS NULL", 'tag_counts'),
    ex(f"Which categories have the most topics tagged {tag}?", f"SELECT c.name, COUNT(DISTINCT t.id) AS topic_count FROM topics t JOIN categories c ON c.id=t.category_id JOIN topic_tags tt ON tt.topic_id=t.id JOIN tags tg ON tg.id=tt.tag_id WHERE tg.name = '{q}' AND t.deleted_at IS NULL GROUP BY c.name ORDER BY topic_count DESC, c.name LIMIT 10", 'tag_categories'),
  ]

for u in users[:40]:
  q=u.replace("'","''")
  examples += [
    ex(f"How many posts has {u} written?", f"SELECT COUNT(*) AS post_count FROM posts p JOIN users u ON u.id=p.user_id WHERE u.username = '{q}' AND p.deleted_at IS NULL", 'user_posts'),
    ex(f"How many likes has {u} given?", f"SELECT COUNT(*) AS likes_given FROM post_actions pa JOIN users u ON u.id=pa.user_id WHERE u.username = '{q}' AND pa.post_action_type_id=2", 'user_likes'),
    ex(f"Which chat channels has {u} posted in?", f"SELECT COALESCE(cc.name, 'DM ' || cc.id::text) AS channel, COUNT(*) AS messages FROM chat_messages cm JOIN chat_channels cc ON cc.id=cm.chat_channel_id JOIN users u ON u.id=cm.user_id WHERE u.username = '{q}' GROUP BY cc.id, cc.name ORDER BY messages DESC, channel LIMIT 20", 'user_chat'),
  ]

for w in words:
  q=w.replace("'","''")
  examples += [
    ex(f"Find topics with {w} in the title.", f"SELECT id, title, created_at FROM topics WHERE title ILIKE '%{q}%' AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 50", 'title_search'),
    ex(f"How many posts mention {w}?", f"SELECT COUNT(*) AS post_count FROM posts WHERE raw ILIKE '%{q}%' AND deleted_at IS NULL", 'post_search'),
    ex(f"How many chat messages mention {w}?", f"SELECT COUNT(*) AS chat_message_count FROM chat_messages WHERE message ILIKE '%{q}%'", 'chat_search'),
  ]

for r in reactions:
  q=r.replace("'","''")
  examples.append(ex(f"Which posts received the most {r} reactions?", f"SELECT p.id AS post_id, t.title, COUNT(ru.id) AS reaction_count FROM discourse_reactions_reaction_users ru JOIN discourse_reactions_reactions rr ON rr.id=ru.reaction_id JOIN posts p ON p.id=ru.post_id JOIN topics t ON t.id=p.topic_id WHERE rr.reaction_value = '{q}' GROUP BY p.id, t.title ORDER BY reaction_count DESC, p.id LIMIT 20", 'reactions'))

examples += [
 ex("How many private messages are there?", "SELECT COUNT(*) AS private_message_topics FROM topics WHERE archetype = 'private_message'", 'pms'),
 ex("Which users started the most private messages?", "SELECT u.username, COUNT(*) AS pm_count FROM topics t JOIN users u ON u.id=t.user_id WHERE t.archetype = 'private_message' GROUP BY u.username ORDER BY pm_count DESC, u.username LIMIT 20", 'pms'),
 ex("Which topics have no replies?", "SELECT t.id, t.title FROM topics t WHERE t.deleted_at IS NULL AND t.posts_count <= 1 ORDER BY t.created_at DESC LIMIT 50", 'no_replies'),
 ex("Which categories have the highest average likes per topic?", "SELECT c.name, AVG(t.like_count)::numeric(10,2) AS avg_likes FROM topics t JOIN categories c ON c.id=t.category_id WHERE t.deleted_at IS NULL GROUP BY c.name ORDER BY avg_likes DESC, c.name LIMIT 20", 'category_likes'),
 ex("How many deleted posts are there?", "SELECT COUNT(*) AS deleted_posts FROM posts WHERE deleted_at IS NOT NULL", 'moderation'),
 ex("How many closed topics are there by category?", "SELECT c.name, COUNT(*) AS closed_topics FROM topics t JOIN categories c ON c.id=t.category_id WHERE t.closed = true GROUP BY c.name ORDER BY closed_topics DESC, c.name", 'moderation'),
]

# Expand by paraphrase-ish deterministic variants
base=list(examples)
for item in base:
    q=item['question']
    if q.startswith('Which'):
        examples.append({**item,'question':q.replace('Which','Show me which',1)})
    if q.startswith('How many'):
        examples.append({**item,'question':q.replace('How many','What is the number of',1)})

random.shuffle(examples)
# de-dupe by question/sql
seen=set(); uniq=[]
for e in examples:
    k=(e['question'],e['sql'])
    if k not in seen:
        seen.add(k); uniq.append(e)
examples=uniq

# Validate a sample/all with EXPLAIN to catch schema drift
valid=[]; invalid=[]
for e in examples:
    cp=subprocess.run(['psql','-d',DB,'-Atc','EXPLAIN '+e['sql']], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    if cp.returncode==0:
        valid.append(e)
    else:
        invalid.append({'example':e,'error':cp.stderr[-500:]})

random.shuffle(valid)
# targets
train_n=min(2500, max(0, len(valid)-400))
dev_n=min(200, max(0, len(valid)-train_n-200))
eval_n=min(200, max(0, len(valid)-train_n-dev_n))
train=valid[:train_n]; dev=valid[train_n:train_n+dev_n]; evals=valid[train_n+dev_n:train_n+dev_n+eval_n]

# Training can tolerate paraphrase-style augmentation over validated SQL. Keep dev/eval untouched.
aug_prefixes = [
    'Write a PostgreSQL query for this Discourse question: ',
    'Generate SQL: ',
    'Return the SQL for: ',
    'Using the schema, answer with SQL only: ',
    'I need a query for: ',
    'Discourse report request: ',
]
base_train = list(train)
idx = 0
while len(train) < 2500 and base_train:
    item = dict(base_train[idx % len(base_train)])
    item['question'] = aug_prefixes[(idx // len(base_train)) % len(aug_prefixes)] + item['question']
    train.append(item)
    idx += 1

def chat_record(e):
    return {'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':'Schema:\n'+SCHEMA+'\n\nQuestion: '+e['question']},{'role':'assistant','content':e['sql']}], 'family': e['family']}

def write_jsonl(path, rows, fn):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w') as f:
        for r in rows:
            f.write(json.dumps(fn(r), ensure_ascii=False)+'\n')
write_jsonl(OUT/'train.jsonl', train, chat_record)
write_jsonl(OUT/'dev.jsonl', dev, chat_record)
write_jsonl(OUT/'eval.jsonl', evals, lambda e:{'question':e['question'],'sql':e['sql'],'family':e['family']})
write_jsonl(OUT/'canonical_eval.jsonl', evals, lambda e:e)
write_json(OUT/'generation_report.json', {'valid':len(valid),'invalid':len(invalid),'train':len(train),'dev':len(dev),'eval':len(evals),'families':sorted(set(e['family'] for e in valid)),'invalid_sample':invalid[:5]})
REPORT.write_text(f"# Dataset Generation Report\n\n- Valid examples: {len(valid)}\n- Invalid examples: {len(invalid)}\n- Train: {len(train)}\n- Dev: {len(dev)}\n- Eval: {len(evals)}\n\nFamilies: {', '.join(sorted(set(e['family'] for e in valid)))}\n")
print(REPORT.read_text())
if len(train) < 100:
    raise SystemExit('too few training examples')
