#!/usr/bin/env python3
from __future__ import annotations
import json, re, subprocess, time
from pathlib import Path
ROOT=Path('/home/agent/work/discourse-sql-ft')
DB='discourse_sql_ft'
SYSTEM='You translate English questions about a Discourse PostgreSQL database into safe read-only PostgreSQL SQL. Output only SQL. No Markdown. No explanation. Use only the provided schema.'
TABLE_RE=re.compile(r'\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)',re.I)
EXAMPLES=[
# badge_queries / badge backfills / badge reports
('badge_queries','Which badges have been granted most recently?',"SELECT ub.id, b.name AS badge_name, u.username, ub.granted_at FROM user_badges ub JOIN badges b ON b.id=ub.badge_id JOIN users u ON u.id=ub.user_id ORDER BY ub.granted_at DESC LIMIT 20;"),
('badge_queries','Which badge posts received the most likes?',"SELECT bp.id AS post_id, bp.topic_id, bp.like_count FROM badge_posts bp WHERE bp.deleted_at IS NULL ORDER BY bp.like_count DESC, bp.id LIMIT 20;"),
('badge_queries','Which users have the most distinct badges?',"SELECT u.username, COUNT(DISTINCT ub.badge_id) AS distinct_badges FROM user_badges ub JOIN users u ON u.id=ub.user_id GROUP BY u.username ORDER BY distinct_badges DESC, u.username LIMIT 20;"),
('badge_queries','Which badges are configured as post-target badges?',"SELECT id, name, grant_count FROM badges WHERE target_posts = true ORDER BY grant_count DESC, name LIMIT 20;"),
# tagging internals
('discourse_tagging','Which tag groups have the most tags?',"SELECT tg.name, COUNT(tgm.tag_id) AS tag_count FROM tag_groups tg LEFT JOIN tag_group_memberships tgm ON tgm.tag_group_id=tg.id GROUP BY tg.name ORDER BY tag_count DESC, tg.name LIMIT 20;"),
('discourse_tagging','Which categories restrict tags through tag groups?',"SELECT c.name AS category, tg.name AS tag_group FROM category_tag_groups ctg JOIN categories c ON c.id=ctg.category_id JOIN tag_groups tg ON tg.id=ctg.tag_group_id ORDER BY c.name, tg.name LIMIT 50;"),
('discourse_tagging','Which categories allow the most specific tags?',"SELECT c.name AS category, COUNT(ct.tag_id) AS tag_count FROM category_tags ct JOIN categories c ON c.id=ct.category_id GROUP BY c.name ORDER BY tag_count DESC, c.name LIMIT 20;"),
('discourse_tagging','Which tag groups allow only one tag per topic?',"SELECT id, name FROM tag_groups WHERE one_per_topic = true ORDER BY name LIMIT 50;"),
('discourse_tagging','Which groups have permissions on tag groups?',"SELECT g.name AS group_name, tg.name AS tag_group, tgp.permission_type FROM tag_group_permissions tgp JOIN groups g ON g.id=tgp.group_id JOIN tag_groups tg ON tg.id=tgp.tag_group_id ORDER BY tg.name, g.name LIMIT 50;"),
# topic view/topic list internals
('topic_view','Which topics are watched by the most users?',"SELECT t.id, t.title, COUNT(*) AS watchers FROM topic_users tu JOIN topics t ON t.id=tu.topic_id WHERE tu.notification_level = 3 AND t.deleted_at IS NULL GROUP BY t.id, t.title ORDER BY watchers DESC, t.id LIMIT 20;"),
('topic_view','Which topics are muted by the most users?',"SELECT t.id, t.title, COUNT(*) AS muted_users FROM topic_users tu JOIN topics t ON t.id=tu.topic_id WHERE tu.notification_level = 0 AND t.deleted_at IS NULL GROUP BY t.id, t.title ORDER BY muted_users DESC, t.id LIMIT 20;"),
('topic_view','Which topics have the most distinct viewers in the last 30 days?',"SELECT t.id, t.title, COUNT(DISTINCT tv.user_id) AS distinct_viewers FROM topic_views tv JOIN topics t ON t.id=tv.topic_id WHERE tv.viewed_at >= CURRENT_DATE - INTERVAL '30 days' AND tv.user_id IS NOT NULL AND t.deleted_at IS NULL GROUP BY t.id, t.title ORDER BY distinct_viewers DESC, t.id LIMIT 20;"),
('topic_view','Which users viewed the most topics in the last 30 days?',"SELECT u.username, COUNT(DISTINCT tv.topic_id) AS topics_viewed FROM topic_views tv JOIN users u ON u.id=tv.user_id WHERE tv.viewed_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY u.username ORDER BY topics_viewed DESC, u.username LIMIT 20;"),
# statistics.rb / user activity
('statistics','How many user actions happened per day in the last 30 days?',"SELECT created_at::date AS day, action_type, COUNT(*) AS action_count FROM user_actions WHERE created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY day, action_type ORDER BY day, action_type;"),
('statistics','Which users performed the most actions in the last 30 days?',"SELECT u.username, COUNT(*) AS action_count FROM user_actions ua JOIN users u ON u.id=ua.user_id WHERE ua.created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY u.username ORDER BY action_count DESC, u.username LIMIT 20;"),
('statistics','Show reading totals by day in the last 30 days.',"SELECT visited_at AS day, SUM(posts_read) AS posts_read, SUM(time_read) AS seconds_read FROM user_visits WHERE visited_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY visited_at ORDER BY visited_at;"),
# reactions plugin report/source
('discourse_reactions','Which reaction values are used most often?',"SELECT rr.reaction_value, COUNT(ru.id) AS usage_count FROM discourse_reactions_reactions rr LEFT JOIN discourse_reactions_reaction_users ru ON ru.reaction_id=rr.id GROUP BY rr.reaction_value ORDER BY usage_count DESC, rr.reaction_value LIMIT 20;"),
('discourse_reactions','Which users reacted the most in the last 30 days?',"SELECT u.username, COUNT(*) AS reaction_count FROM discourse_reactions_reaction_users ru JOIN users u ON u.id=ru.user_id WHERE ru.created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY u.username ORDER BY reaction_count DESC, u.username LIMIT 20;"),
('discourse_reactions','Which posts received the most non-like reactions?',"SELECT p.id AS post_id, t.title, COUNT(*) AS reaction_count FROM discourse_reactions_reaction_users ru JOIN discourse_reactions_reactions rr ON rr.id=ru.reaction_id JOIN posts p ON p.id=ru.post_id JOIN topics t ON t.id=p.topic_id WHERE rr.reaction_value <> 'heart' GROUP BY p.id, t.title ORDER BY reaction_count DESC, p.id LIMIT 20;"),
# topic voting plugin
('topic_voting','Which topics have the most topic votes?',"SELECT t.id, t.title, tvc.votes_count FROM topic_voting_topic_vote_count tvc JOIN topics t ON t.id=tvc.topic_id WHERE t.deleted_at IS NULL ORDER BY tvc.votes_count DESC, t.id LIMIT 20;"),
('topic_voting','Which users cast the most topic votes?',"SELECT u.username, COUNT(*) AS vote_count FROM topic_voting_votes tv JOIN users u ON u.id=tv.user_id WHERE tv.archive = false GROUP BY u.username ORDER BY vote_count DESC, u.username LIMIT 20;"),
('topic_voting','Which categories have topic voting enabled?',"SELECT c.id, c.name FROM topic_voting_category_settings tvcs JOIN categories c ON c.id=tvcs.category_id ORDER BY c.name LIMIT 50;"),
# post voting plugin
('post_voting','Which posts have the highest post-voting score?',"SELECT p.id AS post_id, t.title, SUM(pvv.direction) AS vote_score FROM post_voting_votes pvv JOIN posts p ON p.id=pvv.votable_id AND pvv.votable_type='Post' JOIN topics t ON t.id=p.topic_id WHERE p.deleted_at IS NULL AND t.deleted_at IS NULL GROUP BY p.id, t.title ORDER BY vote_score DESC NULLS LAST, p.id LIMIT 20;"),
('post_voting','Which users cast the most post votes?',"SELECT u.username, COUNT(*) AS vote_count FROM post_voting_votes pvv JOIN users u ON u.id=pvv.user_id GROUP BY u.username ORDER BY vote_count DESC, u.username LIMIT 20;"),
('post_voting','Which posts have the most post-voting comments?',"SELECT p.id AS post_id, t.title, COUNT(pvc.id) AS comment_count FROM post_voting_comments pvc JOIN posts p ON p.id=pvc.post_id JOIN topics t ON t.id=p.topic_id WHERE pvc.deleted_at IS NULL GROUP BY p.id, t.title ORDER BY comment_count DESC, p.id LIMIT 20;"),
# custom fields and source maintenance jobs
('custom_fields','Which user custom fields are most common?',"SELECT name, COUNT(*) AS field_count FROM user_custom_fields GROUP BY name ORDER BY field_count DESC, name LIMIT 20;"),
('custom_fields','Which topic custom fields are most common?',"SELECT name, COUNT(*) AS field_count FROM topic_custom_fields GROUP BY name ORDER BY field_count DESC, name LIMIT 20;"),
('custom_fields','Which post custom fields are most common?',"SELECT name, COUNT(*) AS field_count FROM post_custom_fields GROUP BY name ORDER BY field_count DESC, name LIMIT 20;"),
# email/source utilities
('email_receiver','Which incoming email addresses are rejected most often?',"SELECT from_address, COUNT(*) AS rejection_count FROM incoming_emails WHERE error IS NOT NULL OR rejection_message IS NOT NULL GROUP BY from_address ORDER BY rejection_count DESC, from_address LIMIT 20;"),
('email_receiver','Which incoming email subjects created posts?',"SELECT ie.subject, ie.created_at, p.id AS post_id, t.title FROM incoming_emails ie JOIN posts p ON p.id=ie.post_id JOIN topics t ON t.id=p.topic_id ORDER BY ie.created_at DESC LIMIT 20;"),
# upload security/source
('upload_security','Which secure uploads are largest?',"SELECT id, original_filename, filesize, secure, created_at FROM uploads WHERE secure = true ORDER BY filesize DESC NULLS LAST, id LIMIT 20;"),
('upload_security','Which posts reference the most uploads?',"SELECT p.id AS post_id, t.title, COUNT(ur.upload_id) AS upload_count FROM upload_references ur JOIN posts p ON p.id=ur.target_id AND ur.target_type='Post' JOIN topics t ON t.id=p.topic_id GROUP BY p.id, t.title ORDER BY upload_count DESC, p.id LIMIT 20;"),
# group manager/source
('group_manager','Which groups have the most owners?',"SELECT g.name, COUNT(*) AS owner_count FROM group_users gu JOIN groups g ON g.id=gu.group_id WHERE gu.owner = true GROUP BY g.name ORDER BY owner_count DESC, g.name LIMIT 20;"),
('group_manager','Which groups have had members added most recently?',"SELECT g.name, u.username, gu.created_at FROM group_users gu JOIN groups g ON g.id=gu.group_id JOIN users u ON u.id=gu.user_id ORDER BY gu.created_at DESC LIMIT 20;"),
# auth/source
('auth_tokens','Which users have the most auth token log entries?',"SELECT u.username, COUNT(*) AS auth_log_count FROM user_auth_token_logs utl JOIN users u ON u.id=utl.user_id GROUP BY u.username ORDER BY auth_log_count DESC, u.username LIMIT 20;"),
('auth_tokens','Show recent auth token log actions.',"SELECT utl.id, u.username, utl.action, utl.client_ip, utl.created_at FROM user_auth_token_logs utl LEFT JOIN users u ON u.id=utl.user_id ORDER BY utl.created_at DESC LIMIT 20;"),
]

def psql(sql):
 return subprocess.run(['psql','-d',DB,'-qAt','-c',sql],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True).stdout

def table_schema(ts):
 blocks=[]
 for t in ts:
  rows=psql(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='public' AND table_name='{t}' ORDER BY ordinal_position").splitlines()
  if not rows: continue
  b=[t+'(']
  for r in rows:
   c,typ=r.split('|',1); b.append(f'  {c} {typ},')
  b[-1]=b[-1].rstrip(','); b.append(')'); blocks.append('\n'.join(b))
 return '\n\n'.join(blocks)

def check(sql):
 inner=sql.rstrip(';')
 wrapper="BEGIN READ ONLY; SET LOCAL statement_timeout='5000ms'; SELECT COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb)::text FROM ("+inner+") q; ROLLBACK;"
 cp=subprocess.run(['psql','-d',DB,'-qAt','-c',wrapper],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=8)
 if cp.returncode: raise RuntimeError(cp.stderr)

def main():
 rows=[]; rejected=[]
 for source,q,sql in EXAMPLES:
  try:
   check(sql)
   ts=sorted(set(TABLE_RE.findall(sql)))
   rows.append({'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':'Schema:\n'+table_schema(ts)+'\n\nNotes:\n- This example was mined from Discourse source-code concepts such as badge queries, topic views, tagging, voting plugins, reactions, uploads, email, groups, and auth logs.\n- Use read-only PostgreSQL SELECT SQL.\n\nQuestion: '+q},{'role':'assistant','content':sql}], 'family':'source_mined_'+source, 'source':'Discourse source mined SQL concepts', 'source_name':source, 'coverage_tables':ts})
  except Exception as e:
   rejected.append({'source':source,'question':q,'sql':sql,'error':str(e)})
 out=ROOT/'dataset/source_mined_semantic_pack.jsonl'
 out.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
 with (ROOT/'dataset/train.jsonl').open('a') as f:
  for r in rows: f.write(json.dumps(r,ensure_ascii=False)+'\n')
 rep=ROOT/'reports/source_mined_semantic_pack.md'
 rep.write_text('# Source-mined semantic training pack\n\n'+f'- Candidates: **{len(EXAMPLES)}**\n- Added after execution check: **{len(rows)}**\n- Rejected: **{len(rejected)}**\n- Pack: `{out}`\n\nAll added SQL was executed against `discourse_sql_ft` in a read-only transaction.\n')
 (ROOT/'reports/source_mined_semantic_pack.json').write_text(json.dumps({'candidates':len(EXAMPLES),'added':len(rows),'rejected':len(rejected),'pack':str(out),'rejections':rejected,'finished_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())},indent=2)+'\n')
 print(json.dumps({'candidates':len(EXAMPLES),'added':len(rows),'rejected':len(rejected),'pack':str(out)},indent=2))
if __name__=='__main__': main()
