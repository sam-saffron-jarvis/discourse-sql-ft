# Built-in query/report training pack

- Data Explorer defaults seen: **19**
- Data Explorer defaults added: **19**
- Core report candidates: **48**
- Core report SQL examples added: **48** (45 initial + 3 repaired)
- Rejected after execution check: **3**, all repaired and appended

Pack: `/home/agent/work/discourse-sql-ft/dataset/builtin_queries_reports_pack.jsonl`

Repairs: `/home/agent/work/discourse-sql-ft/dataset/builtin_queries_reports_repairs.jsonl`

All added examples were executed against `discourse_sql_ft` inside a read-only transaction before appending to train. Final appended count: **67** examples — 19 Data Explorer built-ins and 48 core report examples.

## Initial rejections, now repaired

- `core_report` `suspicious_logins`: ERROR:  column "location" does not exist
- `core_report` `top_referred_topics`: ERROR:  column il.topic_id does not exist
- `core_report` `top_traffic_sources`: ERROR:  column "domain" does not exist
