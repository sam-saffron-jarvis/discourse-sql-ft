#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

try:
    import sqlparse
except ImportError:
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
- topic_view_stats is Discourse's per-topic per-day aggregate page-view table.
- topic_view_stats has one row per topic_id and viewed_at date, with anonymous_views and logged_in_views counters.
- Total page views for a topic/date range are SUM(anonymous_views + logged_in_views).
- Discourse's core topic_view_stats report joins topic_view_stats to topics, groups by topic_id and topic title, filters viewed_at BETWEEN start and end dates, and orders by total views descending.
- The /t/:topic_id/view-stats.json endpoint returns per-day stats for one public topic, ordered by viewed_at; its JSON views value is anonymous_views + logged_in_views.
- TopicViewItem.add increments topic_view_stats when a raw topic_views row is accepted. topic_views is lower-level raw deduplicated view data; topic_view_stats is the better table for page views per topic over time.
- Exclude deleted topics with topics.deleted_at IS NULL when reporting public topic rankings.
'''.strip()

EXAMPLES = [
    (
        'What are the top 100 topics by page views in the last 30 days?',
        """
        SELECT tvs.topic_id,
               t.title AS topic_title,
               SUM(tvs.anonymous_views) AS total_anonymous_views,
               SUM(tvs.logged_in_views) AS total_logged_in_views,
               SUM(tvs.anonymous_views + tvs.logged_in_views) AS total_views
        FROM topic_view_stats tvs
        JOIN topics t ON t.id = tvs.topic_id
        WHERE tvs.viewed_at >= CURRENT_DATE - INTERVAL '30 days'
          AND t.deleted_at IS NULL
        GROUP BY tvs.topic_id, t.title
        ORDER BY total_views DESC, tvs.topic_id
        LIMIT 100;
        """,
    ),
    (
        'Show page views per topic this week, split by anonymous and logged-in views.',
        """
        SELECT tvs.topic_id,
               t.title AS topic_title,
               SUM(tvs.anonymous_views) AS anonymous_views,
               SUM(tvs.logged_in_views) AS logged_in_views,
               SUM(tvs.anonymous_views + tvs.logged_in_views) AS total_views
        FROM topic_view_stats tvs
        JOIN topics t ON t.id = tvs.topic_id
        WHERE tvs.viewed_at >= CURRENT_DATE - INTERVAL '7 days'
          AND t.deleted_at IS NULL
        GROUP BY tvs.topic_id, t.title
        ORDER BY total_views DESC, tvs.topic_id
        LIMIT 50;
        """,
    ),
    (
        'For topic 123, show daily page views for the last 30 days.',
        """
        SELECT tvs.viewed_at,
               tvs.anonymous_views,
               tvs.logged_in_views,
               tvs.anonymous_views + tvs.logged_in_views AS total_views
        FROM topic_view_stats tvs
        WHERE tvs.topic_id = 123
          AND tvs.viewed_at >= CURRENT_DATE - INTERVAL '30 days'
        ORDER BY tvs.viewed_at;
        """,
    ),
    (
        'Which topics had the most anonymous page views in the last 30 days?',
        """
        SELECT tvs.topic_id,
               t.title AS topic_title,
               SUM(tvs.anonymous_views) AS anonymous_views
        FROM topic_view_stats tvs
        JOIN topics t ON t.id = tvs.topic_id
        WHERE tvs.viewed_at >= CURRENT_DATE - INTERVAL '30 days'
          AND t.deleted_at IS NULL
        GROUP BY tvs.topic_id, t.title
        ORDER BY anonymous_views DESC, tvs.topic_id
        LIMIT 50;
        """,
    ),
    (
        'Which topics had the most logged-in page views in the last 30 days?',
        """
        SELECT tvs.topic_id,
               t.title AS topic_title,
               SUM(tvs.logged_in_views) AS logged_in_views
        FROM topic_view_stats tvs
        JOIN topics t ON t.id = tvs.topic_id
        WHERE tvs.viewed_at >= CURRENT_DATE - INTERVAL '30 days'
          AND t.deleted_at IS NULL
        GROUP BY tvs.topic_id, t.title
        ORDER BY logged_in_views DESC, tvs.topic_id
        LIMIT 50;
        """,
    ),
    (
        'Show daily total page views across all topics for the last 90 days.',
        """
        SELECT tvs.viewed_at,
               SUM(tvs.anonymous_views) AS anonymous_views,
               SUM(tvs.logged_in_views) AS logged_in_views,
               SUM(tvs.anonymous_views + tvs.logged_in_views) AS total_views
        FROM topic_view_stats tvs
        WHERE tvs.viewed_at >= CURRENT_DATE - INTERVAL '90 days'
        GROUP BY tvs.viewed_at
        ORDER BY tvs.viewed_at;
        """,
    ),
    (
        'Show the core Discourse topic view stats report for a selected date range.',
        """
        SELECT tvs.topic_id,
               t.title AS topic_title,
               SUM(tvs.anonymous_views) AS total_anonymous_views,
               SUM(tvs.logged_in_views) AS total_logged_in_views,
               SUM(tvs.anonymous_views + tvs.logged_in_views) AS total_views
        FROM topic_view_stats tvs
        JOIN topics t ON t.id = tvs.topic_id
        WHERE tvs.viewed_at BETWEEN DATE '2026-01-01' AND DATE '2026-01-31'
          AND t.deleted_at IS NULL
        GROUP BY tvs.topic_id, t.title
        ORDER BY total_views DESC, tvs.topic_id
        LIMIT 100;
        """,
    ),
    (
        'Show the topic view stats report for category 5 including subcategory ids 6 and 7.',
        """
        SELECT tvs.topic_id,
               t.title AS topic_title,
               SUM(tvs.anonymous_views) AS total_anonymous_views,
               SUM(tvs.logged_in_views) AS total_logged_in_views,
               SUM(tvs.anonymous_views + tvs.logged_in_views) AS total_views
        FROM topic_view_stats tvs
        JOIN topics t ON t.id = tvs.topic_id
        WHERE tvs.viewed_at BETWEEN DATE '2026-01-01' AND DATE '2026-01-31'
          AND t.category_id IN (5, 6, 7)
          AND t.deleted_at IS NULL
        GROUP BY tvs.topic_id, t.title
        ORDER BY total_views DESC, tvs.topic_id
        LIMIT 100;
        """,
    ),
    (
        'Which topics have more anonymous than logged-in page views this month?',
        """
        SELECT tvs.topic_id,
               t.title AS topic_title,
               SUM(tvs.anonymous_views) AS anonymous_views,
               SUM(tvs.logged_in_views) AS logged_in_views,
               SUM(tvs.anonymous_views + tvs.logged_in_views) AS total_views
        FROM topic_view_stats tvs
        JOIN topics t ON t.id = tvs.topic_id
        WHERE tvs.viewed_at >= date_trunc('month', CURRENT_DATE)::date
          AND t.deleted_at IS NULL
        GROUP BY tvs.topic_id, t.title
        HAVING SUM(tvs.anonymous_views) > SUM(tvs.logged_in_views)
        ORDER BY anonymous_views DESC, tvs.topic_id
        LIMIT 50;
        """,
    ),
    (
        'Compare a topic total_views aggregate with the topics.views counter.',
        """
        SELECT t.id AS topic_id,
               t.title AS topic_title,
               t.views AS topics_views_counter,
               COALESCE(SUM(tvs.anonymous_views + tvs.logged_in_views), 0) AS stats_total_views
        FROM topics t
        LEFT JOIN topic_view_stats tvs ON tvs.topic_id = t.id
        WHERE t.deleted_at IS NULL
        GROUP BY t.id, t.title, t.views
        ORDER BY stats_total_views DESC, t.id
        LIMIT 50;
        """,
    ),
    (
        'Find topics whose page views spiked yesterday compared with their previous 7 day average.',
        """
        WITH daily_views AS (
          SELECT tvs.topic_id,
                 tvs.viewed_at,
                 SUM(tvs.anonymous_views + tvs.logged_in_views) AS total_views
          FROM topic_view_stats tvs
          WHERE tvs.viewed_at >= CURRENT_DATE - INTERVAL '8 days'
            AND tvs.viewed_at < CURRENT_DATE
          GROUP BY tvs.topic_id, tvs.viewed_at
        ), previous_average AS (
          SELECT dv.topic_id,
                 AVG(dv.total_views) AS avg_previous_views
          FROM daily_views dv
          WHERE dv.viewed_at < CURRENT_DATE - INTERVAL '1 day'
          GROUP BY dv.topic_id
        ), yesterday AS (
          SELECT dv.topic_id,
                 dv.total_views AS yesterday_views
          FROM daily_views dv
          WHERE dv.viewed_at = CURRENT_DATE - INTERVAL '1 day'
        )
        SELECT y.topic_id,
               t.title AS topic_title,
               y.yesterday_views,
               pa.avg_previous_views
        FROM yesterday y
        JOIN previous_average pa ON pa.topic_id = y.topic_id
        JOIN topics t ON t.id = y.topic_id
        WHERE y.yesterday_views > pa.avg_previous_views * 2
          AND t.deleted_at IS NULL
        ORDER BY y.yesterday_views DESC, y.topic_id
        LIMIT 50;
        """,
    ),
    (
        'Show topics with page views in topic_view_stats but no raw topic_views rows in the same date range.',
        """
        SELECT tvs.topic_id,
               t.title AS topic_title,
               SUM(tvs.anonymous_views + tvs.logged_in_views) AS stats_total_views,
               COUNT(tv.topic_id) AS raw_topic_view_rows
        FROM topic_view_stats tvs
        JOIN topics t ON t.id = tvs.topic_id
        LEFT JOIN topic_views tv
          ON tv.topic_id = tvs.topic_id
         AND tv.viewed_at = tvs.viewed_at
        WHERE tvs.viewed_at >= CURRENT_DATE - INTERVAL '30 days'
          AND t.deleted_at IS NULL
        GROUP BY tvs.topic_id, t.title
        HAVING COUNT(tv.topic_id) = 0
        ORDER BY stats_total_views DESC, tvs.topic_id
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
    out = [f'{table}( )' if not rows else f'{table}(']
    if rows:
        for row in rows:
            col, typ = row.split('|', 1)
            out.append(f'  {col} {typ},')
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
    for question, raw_sql in EXAMPLES:
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
                'family': 'semantic_topic_view_stats',
                'coverage_tables': ts,
            }
        )

    out = ROOT / 'dataset/topic_view_stats_semantic_pack.jsonl'
    out.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows))

    with (ROOT / 'dataset/train.jsonl').open('a') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')

    print(json.dumps({'topic_view_stats_semantic_examples_added': len(rows), 'path': str(out)}, indent=2))


if __name__ == '__main__':
    main()
