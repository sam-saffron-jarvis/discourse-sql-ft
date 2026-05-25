#!/usr/bin/env python3
from __future__ import annotations
import json, subprocess, re
from pathlib import Path
ROOT=Path('/home/agent/work/discourse-sql-ft')
DB='discourse_sql_ft'
SYSTEM='You translate English questions about a Discourse PostgreSQL database into safe read-only PostgreSQL SQL. Output only SQL. No Markdown. No explanation. Use only the provided schema.'
TABLE_RE=re.compile(r'\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)',re.I)
EXAMPLES=[
('topic_views','What are the top 20 topics by topic views this week?',"SELECT t.id, t.title, COUNT(*) AS view_count FROM topic_views tv JOIN topics t ON t.id=tv.topic_id WHERE tv.viewed_at >= CURRENT_DATE - INTERVAL '7 days' AND t.deleted_at IS NULL GROUP BY t.id, t.title ORDER BY view_count DESC, t.id LIMIT 20;"),
('topic_views','Which topics had the most anonymous views in the last 30 days?',"SELECT t.id, t.title, COUNT(*) AS anonymous_view_count FROM topic_views tv JOIN topics t ON t.id=tv.topic_id WHERE tv.viewed_at >= CURRENT_DATE - INTERVAL '30 days' AND tv.user_id IS NULL AND t.deleted_at IS NULL GROUP BY t.id, t.title ORDER BY anonymous_view_count DESC, t.id LIMIT 20;"),
('user_visits','Which users spent the most time reading in the last 30 days?',"SELECT u.username, SUM(uv.time_read) AS seconds_read FROM user_visits uv JOIN users u ON u.id=uv.user_id WHERE uv.visited_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY u.username ORDER BY seconds_read DESC, u.username LIMIT 20;"),
('user_visits','Show daily active users for the last 14 days.',"SELECT uv.visited_at, COUNT(DISTINCT uv.user_id) AS active_users FROM user_visits uv WHERE uv.visited_at >= CURRENT_DATE - INTERVAL '14 days' GROUP BY uv.visited_at ORDER BY uv.visited_at;"),
('badges','Which badges have been granted the most?',"SELECT b.id, b.name, b.grant_count FROM badges b WHERE b.enabled = true ORDER BY b.grant_count DESC, b.id LIMIT 20;"),
('user_badges','Which users received the most badges in the last 90 days?',"SELECT u.username, COUNT(*) AS badge_count FROM user_badges ub JOIN users u ON u.id=ub.user_id WHERE ub.granted_at >= CURRENT_DATE - INTERVAL '90 days' GROUP BY u.username ORDER BY badge_count DESC, u.username LIMIT 20;"),
('groups','Which groups have the most users?',"SELECT g.id, g.name, g.user_count FROM groups g ORDER BY g.user_count DESC, g.id LIMIT 20;"),
('group_users','Who are the owners of the moderators group?',"SELECT u.username FROM group_users gu JOIN groups g ON g.id=gu.group_id JOIN users u ON u.id=gu.user_id WHERE g.name = 'moderators' AND gu.owner = true ORDER BY u.username;"),
('uploads','Which users uploaded the most files in the last 30 days?',"SELECT u.username, COUNT(*) AS upload_count, SUM(up.filesize) AS total_bytes FROM uploads up JOIN users u ON u.id=up.user_id WHERE up.created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY u.username ORDER BY upload_count DESC, u.username LIMIT 20;"),
('uploads','Show the largest uploads.',"SELECT up.id, up.original_filename, up.filesize, u.username FROM uploads up LEFT JOIN users u ON u.id=up.user_id ORDER BY up.filesize DESC NULLS LAST, up.id LIMIT 20;"),
('bookmarks','Which users created the most bookmarks?',"SELECT u.username, COUNT(*) AS bookmark_count FROM bookmarks b JOIN users u ON u.id=b.user_id GROUP BY u.username ORDER BY bookmark_count DESC, u.username LIMIT 20;"),
('bookmarks','Show upcoming bookmark reminders.',"SELECT b.id, u.username, b.name, b.reminder_at FROM bookmarks b JOIN users u ON u.id=b.user_id WHERE b.reminder_at IS NOT NULL AND b.reminder_at >= NOW() ORDER BY b.reminder_at LIMIT 20;"),
('notifications','Which users have the most unread notifications?',"SELECT u.username, COUNT(*) AS unread_notifications FROM notifications n JOIN users u ON u.id=n.user_id WHERE n.read = false GROUP BY u.username ORDER BY unread_notifications DESC, u.username LIMIT 20;"),
('notifications','Show notification volume by type in the last 30 days.',"SELECT n.notification_type, COUNT(*) AS notification_count FROM notifications n WHERE n.created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY n.notification_type ORDER BY notification_count DESC, n.notification_type LIMIT 20;"),
('invites','Which users sent the most invites?',"SELECT u.username, COUNT(*) AS invite_count FROM invites i JOIN users u ON u.id=i.invited_by_id WHERE i.deleted_at IS NULL GROUP BY u.username ORDER BY invite_count DESC, u.username LIMIT 20;"),
('invites','Show invites that have expired without being redeemed.',"SELECT i.id, i.email, i.expires_at, i.redemption_count FROM invites i WHERE i.deleted_at IS NULL AND i.expires_at < NOW() AND i.redemption_count = 0 ORDER BY i.expires_at DESC LIMIT 20;"),
('reviewables','Show pending reviewable items with the highest scores.',"SELECT r.id, r.type, r.score, r.target_type, r.target_id, r.created_at FROM reviewables r WHERE r.status = 0 ORDER BY r.score DESC, r.created_at DESC LIMIT 20;"),
('reviewable_scores','Which users created the most reviewable scores in the last 30 days?',"SELECT u.username, COUNT(*) AS score_count FROM reviewable_scores rs JOIN users u ON u.id=rs.user_id WHERE rs.created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY u.username ORDER BY score_count DESC, u.username LIMIT 20;"),
('email_logs','What email types were sent most often in the last 30 days?',"SELECT el.email_type, COUNT(*) AS sent_count FROM email_logs el WHERE el.created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY el.email_type ORDER BY sent_count DESC, el.email_type LIMIT 20;"),
('email_logs','Show recent bounced emails.',"SELECT el.id, el.to_address, el.email_type, el.bounce_error_code, el.created_at FROM email_logs el WHERE el.bounced = true ORDER BY el.created_at DESC LIMIT 20;"),
('incoming_emails','Show recent incoming email rejections.',"SELECT ie.id, ie.from_address, ie.subject, ie.error, ie.rejection_message, ie.created_at FROM incoming_emails ie WHERE ie.error IS NOT NULL OR ie.rejection_message IS NOT NULL ORDER BY ie.created_at DESC LIMIT 20;"),
('user_emails','Find users with multiple email addresses.',"SELECT u.username, COUNT(*) AS email_count FROM user_emails ue JOIN users u ON u.id=ue.user_id GROUP BY u.username HAVING COUNT(*) > 1 ORDER BY email_count DESC, u.username LIMIT 20;"),
('topic_links','Which external domains are linked most often?',"SELECT tl.domain, COUNT(*) AS link_count FROM topic_links tl WHERE tl.internal = false AND tl.domain IS NOT NULL GROUP BY tl.domain ORDER BY link_count DESC, tl.domain LIMIT 20;"),
('topic_links','Show links with the most clicks.',"SELECT tl.url, tl.domain, tl.clicks, t.title FROM topic_links tl LEFT JOIN topics t ON t.id=tl.topic_id ORDER BY tl.clicks DESC NULLS LAST, tl.id LIMIT 20;"),
('topic_timers','Show upcoming topic timers.',"SELECT tt.id, tt.topic_id, t.title, tt.execute_at, tt.public_type FROM topic_timers tt LEFT JOIN topics t ON t.id=tt.topic_id WHERE tt.deleted_at IS NULL AND tt.execute_at >= NOW() ORDER BY tt.execute_at LIMIT 20;"),
('user_options','How many users have private messages disabled?',"SELECT COUNT(*) AS users_with_private_messages_disabled FROM user_options uo WHERE uo.allow_private_messages = false;"),
('user_stats','Which users have read the most posts?',"SELECT u.username, us.posts_read_count, us.time_read FROM user_stats us JOIN users u ON u.id=us.user_id ORDER BY us.posts_read_count DESC, u.username LIMIT 20;"),
('user_stats','Which users have received the most likes according to user stats?',"SELECT u.username, us.likes_received FROM user_stats us JOIN users u ON u.id=us.user_id ORDER BY us.likes_received DESC, u.username LIMIT 20;"),
('web_hooks','Show active web hooks and their last delivery status.',"SELECT wh.id, wh.payload_url, wh.last_delivery_status, wh.status FROM web_hooks wh WHERE wh.active = true ORDER BY wh.id LIMIT 20;"),
('web_hook_events','Show recent failed web hook events.',"SELECT whe.id, whe.web_hook_id, whe.status, whe.duration, whe.created_at FROM web_hook_events whe WHERE whe.status >= 400 ORDER BY whe.created_at DESC LIMIT 20;"),
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
 rows.append({'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':'Schema:\n'+schema+'\n\nNotes:\n- Use read-only PostgreSQL SELECT SQL.\n- For time-windowed views, use topic_views.viewed_at rather than topics.views.\n- Exclude deleted topics with topics.deleted_at IS NULL when listing current topics.\n\nQuestion: '+q},{'role':'assistant','content':sql}], 'family':'semantic_'+family, 'coverage_tables':ts})
out=ROOT/'dataset/semantic_coverage_pack.jsonl'
out.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
with (ROOT/'dataset/train.jsonl').open('a') as f:
 for r in rows: f.write(json.dumps(r,ensure_ascii=False)+'\n')
print(json.dumps({'semantic_examples_added':len(rows),'path':str(out)},indent=2))
