# Discourse SQL fine-tune execution eval

Held-out eval set: 200 English questions. Metric is strict execution-result equality against canonical SQL on the real `discourse_sql_ft` Postgres database. Generated SQL also had to pass the read-only safety gate.

## Summary

| Model | Safe SQL | Executed | Exact result match |
|---|---:|---:|---:|
| base | 200/200 (100.0%) | 154/200 (77.0%) | 0/200 (0.0%) |
| tuned | 200/200 (100.0%) | 200/200 (100.0%) | 199/200 (99.5%) |

Delta exact matches: **+199** for tuned over base.

## Family breakdown

| Family | N | Base exec | Base exact | Tuned exec | Tuned exact |
|---|---:|---:|---:|---:|---:|
| category_avg | 4 | 4 | 0 | 4 | 4 |
| category_counts | 7 | 7 | 0 | 7 | 7 |
| category_likes | 1 | 1 | 0 | 1 | 1 |
| category_users | 10 | 10 | 0 | 10 | 10 |
| chat_activity | 6 | 4 | 0 | 6 | 6 |
| chat_search | 5 | 5 | 0 | 5 | 5 |
| moderation | 2 | 2 | 0 | 2 | 2 |
| no_replies | 1 | 1 | 0 | 1 | 0 |
| pms | 1 | 0 | 0 | 1 | 1 |
| post_search | 5 | 5 | 0 | 5 | 5 |
| reactions | 4 | 0 | 0 | 4 | 4 |
| tag_categories | 27 | 9 | 0 | 27 | 27 |
| tag_counts | 24 | 17 | 0 | 24 | 24 |
| title_search | 5 | 5 | 0 | 5 | 5 |
| top_liked_topics | 11 | 11 | 0 | 11 | 11 |
| top_posters | 13 | 13 | 0 | 13 | 13 |
| user_chat | 25 | 22 | 0 | 25 | 25 |
| user_likes | 25 | 22 | 0 | 25 | 25 |
| user_posts | 24 | 16 | 0 | 24 | 24 |

## Tuned miss

The tuned model had one strict miss: eval #127 (`no_replies`), question: Which topics have no replies?

Canonical:
```sql
SELECT t.id, t.title FROM topics t WHERE t.deleted_at IS NULL AND t.posts_count <= 1 ORDER BY t.created_at DESC LIMIT 50;
```
Predicted:
```sql
SELECT id, title, created_at FROM topics WHERE deleted_at IS NULL AND posts_count <= 1 ORDER BY created_at DESC;
```
This executed, but strict result matching failed because it omitted the canonical `LIMIT 50` and returned `created_at` as an extra column.

## Representative outputs

### #1 `category_users` — Which users started the most topics in Dev?
Base predicted:
```sql
SELECT u.id, u.username, COUNT(t.id) AS topic_count
FROM users u
JOIN topics t ON u.id = t.user_id
JOIN categories c ON t.category_id = c.id
WHERE c.name_lower = 'dev'
GROUP BY u.id, u.username
ORDER BY topic_count DESC
LIMIT 10;
```
Base: exec=True exact=False error=

Tuned predicted:
```sql
SELECT u.username, COUNT(*) AS topic_count FROM topics t JOIN users u ON u.id=t.user_id JOIN categories c ON c.id=t.category_id WHERE c.name = 'Dev' AND t.deleted_at IS NULL GROUP BY u.username ORDER BY topic_count DESC, u.username LIMIT 10;
```
Tuned: exec=True exact=True

### #2 `tag_categories` — Which categories have the most topics tagged solved?
Base predicted:
```sql
SELECT c.id, c.name, COUNT(DISTINCT t.id) AS solved_topic_count
FROM categories c
JOIN topics t ON c.id = t.category_id
JOIN topic_users tu ON t.id = tu.topic_id
WHERE tu.liked = true
GROUP BY c.id, c.name
ORDER BY solved_topic_count DESC
LIMIT 10;
```
Base: exec=True exact=False error=

Tuned predicted:
```sql
SELECT c.name, COUNT(DISTINCT t.id) AS topic_count FROM topics t JOIN categories c ON c.id=t.category_id JOIN topic_tags tt ON tt.topic_id=t.id JOIN tags tg ON tg.id=tt.tag_id WHERE tg.name = 'solved' AND t.deleted_at IS NULL GROUP BY c.name ORDER BY topic_count DESC, c.name LIMIT 10;
```
Tuned: exec=True exact=True

### #3 `tag_counts` — What is the number of topics are tagged accessibility?
Base predicted:
```sql
SELECT COUNT(*) FROM topic_tags JOIN tags ON topic_tags.tag_id = tags.id WHERE tags.name = 'accessibility';
```
Base: exec=True exact=False error=

Tuned predicted:
```sql
SELECT COUNT(DISTINCT t.id) AS topic_count FROM topics t JOIN topic_tags tt ON tt.topic_id=t.id JOIN tags tg ON tg.id=tt.tag_id WHERE tg.name = 'accessibility' AND t.deleted_at IS NULL;
```
Tuned: exec=True exact=True

## Artifacts

- `eval/execution/comparison.json`
- `eval/execution/family_breakdown.json`
- `eval/execution/base/details.jsonl`
- `eval/execution/tuned/details.jsonl`
- `training/qwen35-9b-lora/adapter`
