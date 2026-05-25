#!/usr/bin/env python3
from __future__ import annotations
import json, re, subprocess, time
from pathlib import Path

ROOT=Path('/home/agent/work/discourse-sql-ft')
DISCOURSE=Path('/home/agent/worktrees/discourse-sql-ft')
DB='discourse_sql_ft'
OUT=ROOT/'reports/builtin_queries_reports'
SYSTEM='You translate English questions about a Discourse PostgreSQL database into safe read-only PostgreSQL SQL. Output only SQL. No Markdown. No explanation. Use only the provided schema.'
TABLE_RE=re.compile(r'\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)',re.I)
FORBIDDEN=re.compile(r"\b(insert|update|delete|drop|alter|create|truncate|copy|grant|revoke|call|do|merge|vacuum|analyze)\b",re.I)

def run(cmd,cwd=ROOT,timeout=120,env=None):
    e=None
    if env:
        import os
        e=os.environ.copy(); e.update(env)
    return subprocess.run(cmd,cwd=cwd,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout,check=True,env=e)

def psql(sql):
    return run(['psql','-d',DB,'-qAt','-c',sql]).stdout

def table_exists(t):
    return bool(psql(f"SELECT to_regclass('public.{t}');").strip())

def tables(sql):
    return sorted(set(t for t in TABLE_RE.findall(sql) if table_exists(t)))

def schema_for(ts):
    blocks=[]
    for t in ts:
        rows=psql(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='public' AND table_name='{t}' ORDER BY ordinal_position").splitlines()
        if not rows: continue
        b=[t+'(']
        for r in rows:
            c,typ=r.split('|',1); b.append(f'  {c} {typ},')
        b[-1]=b[-1].rstrip(','); b.append(')')
        blocks.append('\n'.join(b))
    return '\n\n'.join(blocks)

def clean_sql(sql):
    # Remove data-explorer params header comments, replace common params with executable defaults.
    params={
        'months_ago':'1','from_days_ago':'0','duration_days':'30','post_read_count':'100',
        'user':'1','notification_level':'3','group_name':"'trust_level_0'",'start_date':"CURRENT_DATE - INTERVAL '30 days'",'end_date':'CURRENT_DATE',
        'include_pms':'false','poll_name':"'poll'",'post_id':'1','rank_max':'5','enable_null_category':'false'
    }
    lines=[]
    for line in sql.splitlines():
        if line.strip().startswith('-- [params]') or re.match(r'\s*--\s+\w+', line):
            continue
        lines.append(line)
    s='\n'.join(lines).strip()
    s=re.sub(r'\bu\.PRIMARY\b','u."primary"',s,flags=re.I)
    for k,v in sorted(params.items(), key=lambda kv:-len(kv[0])):
        s=re.sub(rf':{k}\b',v,s)
    if not s.endswith(';'): s+=';'
    return s

def safe(sql):
    s=sql.strip().rstrip(';').strip()
    return bool(re.match(r'^(select|with)\b',s,re.I)) and not FORBIDDEN.search(s) and ';' not in s

def exec_ok(sql):
    if not safe(sql): return False,'unsafe'
    inner=sql.strip().rstrip(';')
    wrapper="BEGIN READ ONLY; SET LOCAL statement_timeout='5000ms'; SELECT COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb)::text FROM ("+inner+") q; ROLLBACK;"
    cp=subprocess.run(['psql','-d',DB,'-qAt','-c',wrapper],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=8)
    if cp.returncode!=0:
        return False,(cp.stderr or cp.stdout)[-1000:]
    return True,''

def make_row(question, sql, family, source, name):
    ts=tables(sql)
    return {'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':'Schema:\n'+schema_for(ts)+'\n\nNotes:\n- This example comes from '+source+'.\n- Use read-only PostgreSQL SELECT SQL.\n- Prefer stable ORDER BY tie-breakers and LIMITs for leaderboard/table reports.\n\nQuestion: '+question},{'role':'assistant','content':sql}], 'family':family, 'source':source, 'source_name':name, 'coverage_tables':ts}

def data_explorer_defaults():
    ruby="""
require 'json'
puts JSON.generate(DiscourseDataExplorer::Queries.default.map{|id,q| {id:id, name:q[:name], description:q[:description], sql:q[:sql]}})
"""
    cp=run(['mise','exec','ruby@3.4.6','--','bundle','exec','rails','runner',ruby],cwd=DISCOURSE,timeout=240,env={'DISCOURSE_DEV_DB':DB})
    return json.loads(cp.stdout)

CORE_REPORTS=[
('associated_accounts_by_provider','Which associated account providers have the most users?',"SELECT provider_name, COUNT(*) AS account_count FROM user_associated_accounts GROUP BY provider_name ORDER BY account_count DESC, provider_name LIMIT 20;"),
('bookmarks','How many bookmarks were created per day in the last 30 days?',"SELECT created_at::date AS day, COUNT(*) AS bookmark_count FROM bookmarks WHERE created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY day ORDER BY day;"),
('consolidated_api_requests','Show API request counts by day for the last 30 days.',"SELECT date::date AS day, SUM(count) AS request_count FROM application_requests WHERE req_type IN (6,7,8) AND date >= CURRENT_DATE - INTERVAL '30 days' GROUP BY day ORDER BY day;"),
('consolidated_page_views','Show page view request counts by day for the last 30 days.',"SELECT date::date AS day, SUM(count) AS page_views FROM application_requests WHERE date >= CURRENT_DATE - INTERVAL '30 days' GROUP BY day ORDER BY day;"),
('consolidated_page_views_browser_detection','Show browser page view counts by day for the last 30 days.',"SELECT date::date AS day, req_type, SUM(count) AS page_views FROM application_requests WHERE date >= CURRENT_DATE - INTERVAL '30 days' GROUP BY day, req_type ORDER BY day, req_type;"),
('daily_engaged_users','Show daily engaged users in the last 30 days.',"SELECT created_at::date AS day, COUNT(DISTINCT user_id) AS engaged_users FROM user_actions WHERE created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY day ORDER BY day;"),
('dau_by_mau','Show daily active users and monthly active users for the last 30 days.',"SELECT uv.visited_at AS day, COUNT(DISTINCT uv.user_id) AS dau, (SELECT COUNT(DISTINCT uv2.user_id) FROM user_visits uv2 WHERE uv2.visited_at BETWEEN uv.visited_at - INTERVAL '30 days' AND uv.visited_at) AS mau FROM user_visits uv WHERE uv.visited_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY uv.visited_at ORDER BY uv.visited_at;"),
('emails','Show email volume by type in the last 30 days.',"SELECT email_type, COUNT(*) AS email_count FROM email_logs WHERE created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY email_type ORDER BY email_count DESC, email_type LIMIT 20;"),
('flags','Show daily flag counts in the last 30 days.',"SELECT created_at::date AS day, COUNT(*) AS flag_count FROM post_actions WHERE post_action_type_id IN (3,4,7,8) AND created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY day ORDER BY day;"),
('flags_status','Show flag status counts in the last 30 days.',"SELECT COUNT(*) FILTER (WHERE agreed_at IS NOT NULL) AS agreed, COUNT(*) FILTER (WHERE disagreed_at IS NOT NULL) AS disagreed, COUNT(*) FILTER (WHERE deferred_at IS NOT NULL) AS deferred, COUNT(*) AS total FROM post_actions WHERE post_action_type_id IN (3,4,7,8) AND created_at >= CURRENT_DATE - INTERVAL '30 days';"),
('likes','Show daily like counts in the last 30 days.',"SELECT created_at::date AS day, COUNT(*) AS like_count FROM post_actions WHERE post_action_type_id = 2 AND created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY day ORDER BY day;"),
('mobile_visits','Show mobile visits by day in the last 30 days.',"SELECT visited_at AS day, COUNT(*) AS mobile_visits FROM user_visits WHERE mobile = true AND visited_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY visited_at ORDER BY visited_at;"),
('moderator_warning_private_messages','Show moderator warning private messages in the last 30 days.',"SELECT created_at::date AS day, COUNT(*) AS warning_count FROM topics WHERE archetype='private_message' AND subtype='moderator_warning' AND created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY day ORDER BY day;"),
('moderators_activity','Show moderator activity counts in the last 30 days.',"SELECT u.username, COUNT(*) AS action_count FROM user_histories uh JOIN users u ON u.id=uh.acting_user_id WHERE uh.created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY u.username ORDER BY action_count DESC, u.username LIMIT 20;"),
('new_contributors','Show new contributors by day in the last 30 days.',"SELECT first_post_created_at::date AS day, COUNT(*) AS new_contributors FROM user_stats WHERE first_post_created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY day ORDER BY day;"),
('notify_moderators_private_messages','Show notify moderators private messages by day.',"SELECT created_at::date AS day, COUNT(*) AS notify_moderators_count FROM topics WHERE archetype='private_message' AND subtype='notify_moderators' AND created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY day ORDER BY day;"),
('notify_user_private_messages','Show notify user private messages by day.',"SELECT created_at::date AS day, COUNT(*) AS notify_user_count FROM topics WHERE archetype='private_message' AND subtype='notify_user' AND created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY day ORDER BY day;"),
('post_edits','Show daily post edit counts in the last 30 days.',"SELECT updated_at::date AS day, COUNT(*) AS edited_posts FROM posts WHERE updated_at >= CURRENT_DATE - INTERVAL '30 days' AND version > 1 GROUP BY day ORDER BY day;"),
('posts','Show daily post counts in the last 30 days.',"SELECT created_at::date AS day, COUNT(*) AS post_count FROM posts WHERE deleted_at IS NULL AND created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY day ORDER BY day;"),
('profile_views','Which users have the most profile views?',"SELECT u.username, up.views FROM user_profiles up JOIN users u ON u.id=up.user_id ORDER BY up.views DESC, u.username LIMIT 20;"),
('signups','Show daily signups in the last 30 days.',"SELECT created_at::date AS day, COUNT(*) AS signup_count FROM users WHERE created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY day ORDER BY day;"),
('site_traffic','Show site traffic by request type in the last 30 days.',"SELECT req_type, SUM(count) AS request_count FROM application_requests WHERE date >= CURRENT_DATE - INTERVAL '30 days' GROUP BY req_type ORDER BY request_count DESC, req_type LIMIT 20;"),
('staff_logins','Show recent staff logins.',"SELECT u.username, u.last_seen_at FROM users u WHERE (u.admin = true OR u.moderator = true) ORDER BY u.last_seen_at DESC NULLS LAST LIMIT 20;"),
('storage_stats','Show upload storage by extension.',"SELECT extension, COUNT(*) AS upload_count, SUM(filesize) AS total_bytes FROM uploads GROUP BY extension ORDER BY total_bytes DESC NULLS LAST, extension LIMIT 20;"),
('suspicious_logins','Show suspicious login records.',"SELECT id, user_id, client_ip, location, created_at FROM user_auth_token_logs ORDER BY created_at DESC LIMIT 20;"),
('system_private_messages','Show system private messages by day.',"SELECT created_at::date AS day, COUNT(*) AS message_count FROM topics WHERE archetype='private_message' AND subtype='system_message' AND created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY day ORDER BY day;"),
('time_to_first_response','Show average hours to first response by day.',"SELECT t.created_at::date AS day, AVG(EXTRACT(EPOCH FROM (p.created_at - t.created_at))/3600.0) AS avg_hours_to_first_response FROM topics t JOIN posts p ON p.topic_id=t.id AND p.post_number=2 WHERE t.archetype='regular' AND t.deleted_at IS NULL AND p.deleted_at IS NULL AND t.created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY day ORDER BY day;"),
('top_ignored_users','Which users are ignored or muted most often?',"SELECT u.username, COUNT(*) AS ignore_count FROM ignored_users iu JOIN users u ON u.id=iu.ignored_user_id GROUP BY u.username ORDER BY ignore_count DESC, u.username LIMIT 20;"),
('top_referred_topics','Which referred topics have the most incoming link clicks?',"SELECT t.id, t.title, SUM(il.clicks) AS clicks FROM incoming_links il JOIN topics t ON t.id=il.topic_id WHERE t.deleted_at IS NULL GROUP BY t.id, t.title ORDER BY clicks DESC NULLS LAST, t.id LIMIT 20;"),
('top_referrers','Which users referred the most visits?',"SELECT u.username, COUNT(*) AS referral_count FROM incoming_links il JOIN users u ON u.id=il.user_id GROUP BY u.username ORDER BY referral_count DESC, u.username LIMIT 20;"),
('top_traffic_sources','Which external domains send the most traffic?',"SELECT domain, SUM(incoming_links_count) AS incoming_links_count FROM incoming_domains GROUP BY domain ORDER BY incoming_links_count DESC NULLS LAST, domain LIMIT 20;"),
('top_uploads','Show the largest uploads.',"SELECT id, original_filename, filesize, extension, created_at FROM uploads ORDER BY filesize DESC NULLS LAST, id LIMIT 20;"),
('top_users_by_likes_received','Which users received the most likes?',"SELECT u.username, COUNT(*) AS likes_received FROM post_actions pa JOIN posts p ON p.id=pa.post_id JOIN users u ON u.id=p.user_id WHERE pa.post_action_type_id=2 GROUP BY u.username ORDER BY likes_received DESC, u.username LIMIT 20;"),
('top_users_by_likes_received_from_a_variety_of_people','Which users received likes from the most distinct people?',"SELECT u.username, COUNT(DISTINCT pa.user_id) AS distinct_likers FROM post_actions pa JOIN posts p ON p.id=pa.post_id JOIN users u ON u.id=p.user_id WHERE pa.post_action_type_id=2 GROUP BY u.username ORDER BY distinct_likers DESC, u.username LIMIT 20;"),
('top_users_by_likes_received_from_inferior_trust_level','Which users received the most likes from lower trust level users?',"SELECT receiver.username, COUNT(*) AS likes_from_lower_trust FROM post_actions pa JOIN posts p ON p.id=pa.post_id JOIN users receiver ON receiver.id=p.user_id JOIN users giver ON giver.id=pa.user_id WHERE pa.post_action_type_id=2 AND giver.trust_level < receiver.trust_level GROUP BY receiver.username ORDER BY likes_from_lower_trust DESC, receiver.username LIMIT 20;"),
('topic_view_stats','Which topics have the most views in the last 30 days?',"SELECT t.id, t.title, COUNT(*) AS view_count FROM topic_views tv JOIN topics t ON t.id=tv.topic_id WHERE tv.viewed_at >= CURRENT_DATE - INTERVAL '30 days' AND t.deleted_at IS NULL GROUP BY t.id, t.title ORDER BY view_count DESC, t.id LIMIT 20;"),
('topics','Show daily topic counts in the last 30 days.',"SELECT created_at::date AS day, COUNT(*) AS topic_count FROM topics WHERE deleted_at IS NULL AND created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY day ORDER BY day;"),
('topics_with_no_response','Show topics with no response.',"SELECT id, title, created_at FROM topics WHERE deleted_at IS NULL AND posts_count <= 1 ORDER BY created_at DESC LIMIT 50;"),
('trending_search','Which search terms are most common?',"SELECT term, COUNT(*) AS searches FROM search_logs WHERE created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY term ORDER BY searches DESC, term LIMIT 20;"),
('trust_level_growth','Show user counts by trust level.',"SELECT trust_level, COUNT(*) AS user_count FROM users GROUP BY trust_level ORDER BY trust_level;"),
('user_flagging_ratio','Which users have the highest flagging ratio?',"SELECT u.username, COUNT(*) FILTER (WHERE pa.user_id=u.id) AS flags_given, COUNT(*) FILTER (WHERE p.user_id=u.id) AS flags_received FROM users u LEFT JOIN post_actions pa ON pa.user_id=u.id AND pa.post_action_type_id IN (3,4,7,8) LEFT JOIN posts p ON p.user_id=u.id GROUP BY u.username ORDER BY flags_given DESC, u.username LIMIT 20;"),
('user_to_user_private_messages','Show user to user private messages by day.',"SELECT created_at::date AS day, COUNT(*) AS pm_count FROM topics WHERE archetype='private_message' AND subtype='user_to_user' AND created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY day ORDER BY day;"),
('user_to_user_private_messages_with_replies','Show user to user private messages with replies by day.',"SELECT created_at::date AS day, COUNT(*) AS pm_count FROM topics WHERE archetype='private_message' AND subtype='user_to_user' AND posts_count > 1 AND created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY day ORDER BY day;"),
('users_by_trust_level','Show users by trust level.',"SELECT trust_level, COUNT(*) AS user_count FROM users GROUP BY trust_level ORDER BY trust_level;"),
('users_by_type','Show users by type.',"SELECT CASE WHEN admin THEN 'admin' WHEN moderator THEN 'moderator' WHEN staged THEN 'staged' ELSE 'regular' END AS user_type, COUNT(*) AS user_count FROM users GROUP BY user_type ORDER BY user_count DESC, user_type;"),
('visits','Show visits by day in the last 30 days.',"SELECT visited_at AS day, COUNT(*) AS visits FROM user_visits WHERE visited_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY visited_at ORDER BY visited_at;"),
('web_crawlers','Show web crawler requests by day.',"SELECT date::date AS day, user_agent, SUM(count) AS request_count FROM web_crawler_requests WHERE date >= CURRENT_DATE - INTERVAL '30 days' GROUP BY day, user_agent ORDER BY day DESC, request_count DESC LIMIT 100;"),
('web_hook_events_daily_aggregate','Show webhook event counts by day and status.',"SELECT created_at::date AS day, status, COUNT(*) AS event_count FROM web_hook_events WHERE created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY day, status ORDER BY day, status;")
]

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    rows=[]; rejected=[]; de_total=0
    for q in data_explorer_defaults():
        de_total+=1
        sql=clean_sql(q['sql'])
        ok,err=exec_ok(sql)
        if ok:
            question=f"Data Explorer built-in query: {q['name']}. {q.get('description') or ''}".strip()
            rows.append(make_row(question, sql, 'data_explorer_builtin', 'Discourse Data Explorer built-in queries', q['name']))
        else:
            rejected.append({'source':'data_explorer','name':q['name'],'sql':sql,'error':err})
    for name,question,sql in CORE_REPORTS:
        ok,err=exec_ok(sql)
        if ok:
            rows.append(make_row(question, sql, 'discourse_core_report', 'Discourse core reports', name))
        else:
            rejected.append({'source':'core_report','name':name,'sql':sql,'error':err})
    out=ROOT/'dataset/builtin_queries_reports_pack.jsonl'
    out.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
    with (ROOT/'dataset/train.jsonl').open('a') as f:
        for r in rows: f.write(json.dumps(r,ensure_ascii=False)+'\n')
    summary={'started_finished_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'data_explorer_defaults_seen':de_total,'core_report_candidates':len(CORE_REPORTS),'examples_added':len(rows),'data_explorer_added':sum(1 for r in rows if r['family']=='data_explorer_builtin'),'core_reports_added':sum(1 for r in rows if r['family']=='discourse_core_report'),'rejected':len(rejected),'pack':str(out)}
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    (OUT/'rejected.json').write_text(json.dumps(rejected,indent=2)+'\n')
    md=['# Built-in query/report training pack','',f"- Data Explorer defaults seen: **{summary['data_explorer_defaults_seen']}**",f"- Data Explorer defaults added: **{summary['data_explorer_added']}**",f"- Core report candidates: **{summary['core_report_candidates']}**",f"- Core report SQL examples added: **{summary['core_reports_added']}**",f"- Rejected after execution check: **{summary['rejected']}**",'',f"Pack: `{out}`",'', 'All added examples were executed against `discourse_sql_ft` inside a read-only transaction before appending to train.']
    if rejected:
        md += ['', '## Rejections', '']
        for r in rejected: md.append(f"- `{r['source']}` `{r['name']}`: {r['error'].splitlines()[0] if r['error'] else 'unknown'}")
    (ROOT/'reports/builtin_queries_reports.md').write_text('\n'.join(md)+'\n')
    print(json.dumps(summary,indent=2))

if __name__=='__main__': main()
