#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

try:
    import sqlparse
except ImportError:  # keep the script usable even outside the project venv
    sqlparse = None

ROOT = Path('/home/agent/work/discourse-sql-ft')
DB = 'discourse_sql_ft'
SYSTEM = (
    'You translate English questions about a Discourse PostgreSQL database into safe read-only '
    'PostgreSQL SQL. Output only SQL. No Markdown. No explanation. Use only the provided schema.'
)
TABLE_RE = re.compile(r'\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)', re.I)

NOTES = '''
- Use read-only PostgreSQL SELECT SQL.
- post_actions is the event table for likes and post flags. Join post_actions.post_action_type_id to post_action_types.id for type names.
- post_action_types id/name_key mappings from Discourse seed data: 2=like, 3=off_topic, 4=inappropriate, 6=notify_user, 7=notify_moderators, 8=spam.
- In post_action_types, is_flag=true means flag types; like (id 2) is not a flag.
- flags is a lookup/config table for flag definitions, not the event log. It includes 2=like, 3=off_topic, 4=inappropriate, 6=notify_user, 7=notify_moderators, 8=spam, 9=needs_approval, 10=illegal.
- For active/non-deleted post actions, filter post_actions.deleted_at IS NULL.
- For flags attached to posts/topics, join post_actions -> posts -> topics.
- post_actions.user_id is the user who performed the like or flag. posts.user_id is the author of the flagged/liked post.
- user_actions is Discourse's user activity stream table.
- UserAction type mappings from app/models/user_action.rb: 1=like, 2=was_liked, 4=new_topic, 5=reply, 6=response, 7=mention, 9=quote, 11=edit, 12=new_private_message, 13=got_private_message, 15=solved, 16=assigned, 17=linked.
- UserAction.USER_ACTED_TYPES are 1, 4, 5, 12 for daily engaged users in source.
- user_actions.user_id is the owner/subject of the activity row; acting_user_id is the actor for notification-style rows.
'''.strip()

EXAMPLES = [
    (
        'post_action_flags',
        'How many off-topic flags were created in the last 7 days?',
        """
        SELECT COUNT(*) AS off_topic_flags
        FROM post_actions pa
        WHERE pa.post_action_type_id = 3
          AND pa.deleted_at IS NULL
          AND pa.created_at >= CURRENT_DATE - INTERVAL '7 days';
        """,
    ),
    (
        'post_action_flags',
        'Show the topics with the most off-topic flags this week.',
        """
        SELECT t.id,
               t.title,
               COUNT(*) AS off_topic_flags
        FROM post_actions pa
        JOIN posts p ON p.id = pa.post_id
        JOIN topics t ON t.id = p.topic_id
        WHERE pa.post_action_type_id = 3
          AND pa.deleted_at IS NULL
          AND pa.created_at >= CURRENT_DATE - INTERVAL '7 days'
          AND p.deleted_at IS NULL
          AND t.deleted_at IS NULL
        GROUP BY t.id, t.title
        ORDER BY off_topic_flags DESC, t.id
        LIMIT 20;
        """,
    ),
    (
        'post_action_flags',
        'Which posts received spam flags in the last 30 days?',
        """
        SELECT p.id AS post_id,
               p.topic_id,
               p.post_number,
               t.title,
               COUNT(*) AS spam_flags
        FROM post_actions pa
        JOIN posts p ON p.id = pa.post_id
        JOIN topics t ON t.id = p.topic_id
        WHERE pa.post_action_type_id = 8
          AND pa.deleted_at IS NULL
          AND pa.created_at >= CURRENT_DATE - INTERVAL '30 days'
          AND p.deleted_at IS NULL
          AND t.deleted_at IS NULL
        GROUP BY p.id, p.topic_id, p.post_number, t.title
        ORDER BY spam_flags DESC, p.id
        LIMIT 50;
        """,
    ),
    (
        'post_action_flags',
        'Which users had the most spam flags placed on their posts this month?',
        """
        SELECT u.id AS user_id,
               u.username,
               COUNT(*) AS spam_flags_received
        FROM post_actions pa
        JOIN posts p ON p.id = pa.post_id
        JOIN users u ON u.id = p.user_id
        WHERE pa.post_action_type_id = 8
          AND pa.deleted_at IS NULL
          AND pa.created_at >= date_trunc('month', CURRENT_DATE)
          AND p.deleted_at IS NULL
        GROUP BY u.id, u.username
        ORDER BY spam_flags_received DESC, u.id
        LIMIT 20;
        """,
    ),
    (
        'post_action_flags',
        'List recent inappropriate flags with the flagger and flagged post author.',
        """
        SELECT pa.id AS post_action_id,
               pa.created_at,
               flagger.username AS flagger_username,
               author.username AS flagged_author_username,
               p.id AS post_id,
               p.topic_id,
               p.post_number
        FROM post_actions pa
        JOIN posts p ON p.id = pa.post_id
        JOIN users flagger ON flagger.id = pa.user_id
        JOIN users author ON author.id = p.user_id
        WHERE pa.post_action_type_id = 4
          AND pa.deleted_at IS NULL
        ORDER BY pa.created_at DESC
        LIMIT 50;
        """,
    ),
    (
        'post_action_flags',
        'How many notify-user flags were submitted each day in the last 30 days?',
        """
        SELECT pa.created_at::date AS day,
               COUNT(*) AS notify_user_flags
        FROM post_actions pa
        WHERE pa.post_action_type_id = 6
          AND pa.deleted_at IS NULL
          AND pa.created_at >= CURRENT_DATE - INTERVAL '30 days'
        GROUP BY pa.created_at::date
        ORDER BY day DESC;
        """,
    ),
    (
        'post_action_flags',
        'How many notify-moderators flags were submitted each day in the last 30 days?',
        """
        SELECT pa.created_at::date AS day,
               COUNT(*) AS notify_moderators_flags
        FROM post_actions pa
        WHERE pa.post_action_type_id = 7
          AND pa.deleted_at IS NULL
          AND pa.created_at >= CURRENT_DATE - INTERVAL '30 days'
        GROUP BY pa.created_at::date
        ORDER BY day DESC;
        """,
    ),
    (
        'post_action_flags',
        'Show all post flags by type for the last 30 days.',
        """
        SELECT pat.id AS post_action_type_id,
               pat.name_key,
               COUNT(pa.id) AS flag_count
        FROM post_action_types pat
        LEFT JOIN post_actions pa
          ON pa.post_action_type_id = pat.id
         AND pa.deleted_at IS NULL
         AND pa.created_at >= CURRENT_DATE - INTERVAL '30 days'
        WHERE pat.is_flag = true
        GROUP BY pat.id, pat.name_key
        ORDER BY flag_count DESC, pat.id;
        """,
    ),
    (
        'post_action_flags',
        'Show flag counts by flagger and flag type for the last 30 days.',
        """
        SELECT u.id AS flagger_id,
               u.username AS flagger_username,
               pat.name_key AS flag_type,
               COUNT(*) AS flag_count
        FROM post_actions pa
        JOIN post_action_types pat ON pat.id = pa.post_action_type_id
        JOIN users u ON u.id = pa.user_id
        WHERE pat.is_flag = true
          AND pa.deleted_at IS NULL
          AND pa.created_at >= CURRENT_DATE - INTERVAL '30 days'
        GROUP BY u.id, u.username, pat.name_key
        ORDER BY flag_count DESC, u.id, pat.name_key
        LIMIT 100;
        """,
    ),
    (
        'post_action_flags',
        'Which users placed the most flags in the last 90 days?',
        """
        SELECT u.id AS user_id,
               u.username,
               COUNT(*) AS flags_created
        FROM post_actions pa
        JOIN post_action_types pat ON pat.id = pa.post_action_type_id
        JOIN users u ON u.id = pa.user_id
        WHERE pat.is_flag = true
          AND pa.deleted_at IS NULL
          AND pa.created_at >= CURRENT_DATE - INTERVAL '90 days'
        GROUP BY u.id, u.username
        ORDER BY flags_created DESC, u.id
        LIMIT 20;
        """,
    ),
    (
        'post_action_flags',
        'Which posts have the most active flags across all flag types?',
        """
        SELECT p.id AS post_id,
               p.topic_id,
               p.post_number,
               t.title,
               COUNT(*) AS active_flags
        FROM post_actions pa
        JOIN post_action_types pat ON pat.id = pa.post_action_type_id
        JOIN posts p ON p.id = pa.post_id
        JOIN topics t ON t.id = p.topic_id
        WHERE pat.is_flag = true
          AND pa.deleted_at IS NULL
          AND p.deleted_at IS NULL
          AND t.deleted_at IS NULL
        GROUP BY p.id, p.topic_id, p.post_number, t.title
        ORDER BY active_flags DESC, p.id
        LIMIT 50;
        """,
    ),
    (
        'post_action_flags',
        'Compare post action type definitions with the flag lookup table.',
        """
        SELECT pat.id,
               pat.name_key AS post_action_type,
               pat.is_flag,
               f.name AS flag_name,
               f.enabled AS flag_enabled,
               f.require_message
        FROM post_action_types pat
        LEFT JOIN flags f ON f.id = pat.id
        ORDER BY pat.id;
        """,
    ),
    (
        'post_action_flags',
        'List enabled flag definitions from the flags lookup table.',
        """
        SELECT f.id,
               f.name,
               f.notify_type,
               f.auto_action_type,
               f.require_message,
               f.applies_to
        FROM flags f
        WHERE f.enabled = true
        ORDER BY f.position NULLS LAST, f.id;
        """,
    ),
    (
        'post_action_likes',
        'Which posts received the most likes in the last 30 days?',
        """
        SELECT p.id AS post_id,
               p.topic_id,
               p.post_number,
               t.title,
               COUNT(*) AS likes
        FROM post_actions pa
        JOIN posts p ON p.id = pa.post_id
        JOIN topics t ON t.id = p.topic_id
        WHERE pa.post_action_type_id = 2
          AND pa.deleted_at IS NULL
          AND pa.created_at >= CURRENT_DATE - INTERVAL '30 days'
          AND p.deleted_at IS NULL
          AND t.deleted_at IS NULL
        GROUP BY p.id, p.topic_id, p.post_number, t.title
        ORDER BY likes DESC, p.id
        LIMIT 50;
        """,
    ),
    (
        'post_action_likes',
        'Which users gave the most likes this month?',
        """
        SELECT u.id AS user_id,
               u.username,
               COUNT(*) AS likes_given
        FROM post_actions pa
        JOIN users u ON u.id = pa.user_id
        WHERE pa.post_action_type_id = 2
          AND pa.deleted_at IS NULL
          AND pa.created_at >= date_trunc('month', CURRENT_DATE)
        GROUP BY u.id, u.username
        ORDER BY likes_given DESC, u.id
        LIMIT 20;
        """,
    ),
    (
        'post_action_likes',
        'Which users received the most likes on their posts this month?',
        """
        SELECT author.id AS user_id,
               author.username,
               COUNT(*) AS likes_received
        FROM post_actions pa
        JOIN posts p ON p.id = pa.post_id
        JOIN users author ON author.id = p.user_id
        WHERE pa.post_action_type_id = 2
          AND pa.deleted_at IS NULL
          AND pa.created_at >= date_trunc('month', CURRENT_DATE)
          AND p.deleted_at IS NULL
        GROUP BY author.id, author.username
        ORDER BY likes_received DESC, author.id
        LIMIT 20;
        """,
    ),
    (
        'user_action_types',
        'Show user activity counts by UserAction type in the last 30 days.',
        """
        SELECT CASE ua.action_type
                 WHEN 1 THEN 'like'
                 WHEN 2 THEN 'was_liked'
                 WHEN 4 THEN 'new_topic'
                 WHEN 5 THEN 'reply'
                 WHEN 6 THEN 'response'
                 WHEN 7 THEN 'mention'
                 WHEN 9 THEN 'quote'
                 WHEN 11 THEN 'edit'
                 WHEN 12 THEN 'new_private_message'
                 WHEN 13 THEN 'got_private_message'
                 WHEN 15 THEN 'solved'
                 WHEN 16 THEN 'assigned'
                 WHEN 17 THEN 'linked'
                 ELSE 'unknown'
               END AS action_type_name,
               ua.action_type,
               COUNT(*) AS action_count
        FROM user_actions ua
        WHERE ua.created_at >= CURRENT_DATE - INTERVAL '30 days'
        GROUP BY ua.action_type
        ORDER BY action_count DESC, ua.action_type;
        """,
    ),
    (
        'user_action_types',
        'Count daily engaged users using Discourse USER_ACTED_TYPES for the last 30 days.',
        """
        SELECT ua.created_at::date AS day,
               COUNT(DISTINCT ua.user_id) AS engaged_users
        FROM user_actions ua
        WHERE ua.action_type IN (1, 4, 5, 12)
          AND ua.created_at >= CURRENT_DATE - INTERVAL '30 days'
        GROUP BY ua.created_at::date
        ORDER BY day DESC;
        """,
    ),
    (
        'user_action_types',
        'Which users created the most topics according to user_actions this month?',
        """
        SELECT u.id AS user_id,
               u.username,
               COUNT(*) AS new_topics
        FROM user_actions ua
        JOIN users u ON u.id = ua.user_id
        WHERE ua.action_type = 4
          AND ua.created_at >= date_trunc('month', CURRENT_DATE)
        GROUP BY u.id, u.username
        ORDER BY new_topics DESC, u.id
        LIMIT 20;
        """,
    ),
    (
        'user_action_types',
        'Which users replied the most according to user_actions this month?',
        """
        SELECT u.id AS user_id,
               u.username,
               COUNT(*) AS replies
        FROM user_actions ua
        JOIN users u ON u.id = ua.user_id
        WHERE ua.action_type = 5
          AND ua.created_at >= date_trunc('month', CURRENT_DATE)
        GROUP BY u.id, u.username
        ORDER BY replies DESC, u.id
        LIMIT 20;
        """,
    ),
    (
        'user_action_types',
        'Show recent mentions with the mentioned user and actor.',
        """
        SELECT ua.id AS user_action_id,
               ua.created_at,
               mentioned.username AS mentioned_username,
               actor.username AS acting_username,
               ua.target_topic_id,
               ua.target_post_id
        FROM user_actions ua
        JOIN users mentioned ON mentioned.id = ua.user_id
        LEFT JOIN users actor ON actor.id = ua.acting_user_id
        WHERE ua.action_type = 7
        ORDER BY ua.created_at DESC
        LIMIT 50;
        """,
    ),
    (
        'user_action_types',
        'Show recent quoted-post notifications with target topics and posts.',
        """
        SELECT ua.id AS user_action_id,
               ua.created_at,
               u.username,
               t.title,
               p.post_number
        FROM user_actions ua
        JOIN users u ON u.id = ua.user_id
        LEFT JOIN topics t ON t.id = ua.target_topic_id
        LEFT JOIN posts p ON p.id = ua.target_post_id
        WHERE ua.action_type = 9
        ORDER BY ua.created_at DESC
        LIMIT 50;
        """,
    ),
    (
        'user_action_types',
        'Which users had the most posts edited by someone else in the last 30 days?',
        """
        SELECT target_user.id AS user_id,
               target_user.username,
               COUNT(*) AS edit_notifications
        FROM user_actions ua
        JOIN users target_user ON target_user.id = ua.user_id
        WHERE ua.action_type = 11
          AND ua.acting_user_id IS NOT NULL
          AND ua.acting_user_id <> ua.user_id
          AND ua.created_at >= CURRENT_DATE - INTERVAL '30 days'
        GROUP BY target_user.id, target_user.username
        ORDER BY edit_notifications DESC, target_user.id
        LIMIT 20;
        """,
    ),
    (
        'user_action_types',
        'Show private message activity counts by sent and received actions this month.',
        """
        SELECT CASE ua.action_type
                 WHEN 12 THEN 'new_private_message'
                 WHEN 13 THEN 'got_private_message'
               END AS private_message_action,
               COUNT(*) AS action_count
        FROM user_actions ua
        WHERE ua.action_type IN (12, 13)
          AND ua.created_at >= date_trunc('month', CURRENT_DATE)
        GROUP BY ua.action_type
        ORDER BY ua.action_type;
        """,
    ),
    (
        'user_action_types',
        'Which users received the most likes according to UserAction WAS_LIKED this month?',
        """
        SELECT u.id AS user_id,
               u.username,
               COUNT(*) AS was_liked_actions
        FROM user_actions ua
        JOIN users u ON u.id = ua.user_id
        WHERE ua.action_type = 2
          AND ua.created_at >= date_trunc('month', CURRENT_DATE)
        GROUP BY u.id, u.username
        ORDER BY was_liked_actions DESC, u.id
        LIMIT 20;
        """,
    ),
    (
        'user_action_types',
        'Which users gave the most likes according to UserAction LIKE this month?',
        """
        SELECT u.id AS user_id,
               u.username,
               COUNT(*) AS like_actions
        FROM user_actions ua
        JOIN users u ON u.id = ua.user_id
        WHERE ua.action_type = 1
          AND ua.created_at >= date_trunc('month', CURRENT_DATE)
        GROUP BY u.id, u.username
        ORDER BY like_actions DESC, u.id
        LIMIT 20;
        """,
    ),
    (
        'user_action_types',
        'Show solved-answer UserAction rows from the last 90 days.',
        """
        SELECT ua.id AS user_action_id,
               ua.created_at,
               u.username,
               t.title,
               p.post_number
        FROM user_actions ua
        JOIN users u ON u.id = ua.user_id
        LEFT JOIN topics t ON t.id = ua.target_topic_id
        LEFT JOIN posts p ON p.id = ua.target_post_id
        WHERE ua.action_type = 15
          AND ua.created_at >= CURRENT_DATE - INTERVAL '90 days'
        ORDER BY ua.created_at DESC
        LIMIT 50;
        """,
    ),
    (
        'user_action_types',
        'Show assigned UserAction rows from the last 90 days.',
        """
        SELECT ua.id AS user_action_id,
               ua.created_at,
               assigned_user.username AS assigned_user,
               actor.username AS acting_username,
               ua.target_topic_id,
               ua.target_post_id
        FROM user_actions ua
        JOIN users assigned_user ON assigned_user.id = ua.user_id
        LEFT JOIN users actor ON actor.id = ua.acting_user_id
        WHERE ua.action_type = 16
          AND ua.created_at >= CURRENT_DATE - INTERVAL '90 days'
        ORDER BY ua.created_at DESC
        LIMIT 50;
        """,
    ),
]


def psql(sql: str) -> str:
    return subprocess.run(
        ['psql', '-d', DB, '-qAt', '-c', sql],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout


def table_schema(table: str) -> str:
    rows = psql(
        "SELECT column_name, data_type "
        "FROM information_schema.columns "
        "WHERE table_schema='public' "
        f"AND table_name='{table}' "
        "ORDER BY ordinal_position"
    ).splitlines()
    out = [f'{table}(']
    for row in rows:
        col, typ = row.split('|', 1)
        out.append(f'  {col} {typ},')
    if len(out) > 1:
        out[-1] = out[-1].rstrip(',')
    out.append(')')
    return '\n'.join(out)


def tables(sql: str) -> list[str]:
    return sorted(set(match.group(1) for match in TABLE_RE.finditer(sql)))


def clean_sql(sql: str) -> str:
    sql = re.sub(r'\n[ \t]+', '\n', sql.strip()).strip()
    if sqlparse is not None:
        sql = sqlparse.format(sql, keyword_case='upper', identifier_case=None, reindent=True).strip()
    return sql.rstrip(';') + ';'


def check(sql: str) -> None:
    inner = sql.rstrip(';')
    wrapper = (
        "BEGIN READ ONLY; "
        "SET LOCAL statement_timeout='3000ms'; "
        "SELECT COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb)::text "
        f"FROM ({inner}) q; "
        "ROLLBACK;"
    )
    cp = subprocess.run(
        ['psql', '-d', DB, '-qAt', '-c', wrapper],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=8,
    )
    if cp.returncode:
        raise RuntimeError(cp.stderr)


def main() -> None:
    rows = []
    for family, question, raw_sql in EXAMPLES:
        sql = clean_sql(raw_sql)
        check(sql)
        ts = tables(sql)
        schema = '\n\n'.join(table_schema(t) for t in ts)
        rows.append(
            {
                'messages': [
                    {'role': 'system', 'content': SYSTEM},
                    {
                        'role': 'user',
                        'content': 'Schema:\n' + schema + '\n\nNotes:\n' + NOTES + '\n\nQuestion: ' + question,
                    },
                    {'role': 'assistant', 'content': sql},
                ],
                'family': 'semantic_action_types',
                'semantic_family': family,
                'coverage_tables': ts,
            }
        )

    out = ROOT / 'dataset/action_type_semantic_pack.jsonl'
    out.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows))

    train = ROOT / 'dataset/train.jsonl'
    with train.open('a') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')

    print(
        json.dumps(
            {
                'action_type_semantic_examples_added': len(rows),
                'path': str(out),
                'families': sorted({row['semantic_family'] for row in rows}),
            },
            indent=2,
        )
    )


if __name__ == '__main__':
    main()
