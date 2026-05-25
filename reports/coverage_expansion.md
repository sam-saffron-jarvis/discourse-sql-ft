# Discourse SQL dataset coverage expansion

Started: `2026-05-25T00:15:25Z` UTC
Finished: `2026-05-25T00:15:33Z` UTC

## Summary

- Schema base tables: **311**
- Train table coverage: **11 → 311**
- Any-split table coverage: **11 → 311**
- Examples appended to train: **638** (597 initial + 3 reserved-keyword repairs + 30 semantic high-value examples + 8 AI audit examples)
- Targeted missing train tables: **300**
- Targeted tables with source hits: **290**
- Rejected generated examples: **3**, all repaired and appended in `dataset/coverage_expansion_repair.jsonl`

## Files

- Backup: `/home/agent/work/discourse-sql-ft/dataset/train.before-coverage-expansion.1779668133.jsonl`
- Added examples: `/home/agent/work/discourse-sql-ft/dataset/coverage_expansion.jsonl`
- Coverage table: `/home/agent/work/discourse-sql-ft/reports/coverage_expansion/coverage_by_table.json`
- Source hits: `/home/agent/work/discourse-sql-ft/reports/coverage_expansion/source_hits.json`
- Rejections: `/home/agent/work/discourse-sql-ft/reports/coverage_expansion/rejected.json`
- Repairs: `/home/agent/work/discourse-sql-ft/dataset/coverage_expansion_repair.jsonl`
- Semantic high-value pack: `/home/agent/work/discourse-sql-ft/dataset/semantic_coverage_pack.jsonl`
- Semantic AI audit pack: `/home/agent/work/discourse-sql-ft/dataset/semantic_ai_audit_pack.jsonl`
- Final audit: `/home/agent/work/discourse-sql-ft/reports/coverage_expansion/final_audit.json`

## Caveat

This pass guarantees executable training coverage for every base table that was missing from train; a final audit found 311/311 schema base tables covered in `dataset/train.jsonl`. Many generated examples are deliberately simple count/sample queries. That gives the model table/column exposure; it does not replace hand-written semantic admin questions for important tables.

I added a small semantic pack for high-value admin/support concepts after the blanket coverage pass: `topic_views`, `user_visits`, badges, groups, uploads, bookmarks, notifications, invites, reviewables, email, user emails, topic links/timers, user options/stats, and web hooks. This includes the corrected `topic_views.viewed_at` pattern for weekly topic views.

## AI audit semantic coverage

Added 8 executable examples covering:

- feature request counts from `ai_api_audit_logs`
- language-model token usage
- per-user AI token consumption
- failed AI API requests by `response_status`
- slowest AI features by `duration_msecs`
- topics generating AI API calls
- daily rolled-up AI usage by feature from `ai_api_request_stats`
- monthly rolled-up AI usage by user

## Example new rows

### `ad_plugin_house_ads`
How many ad plugin house ads records are there?
```sql
SELECT COUNT(*) AS row_count FROM ad_plugin_house_ads;
```

### `ad_plugin_house_ads`
Show the 20 most recent ad plugin house ads records.
```sql
SELECT id, name, created_at, updated_at, html, visible_to_logged_in_users FROM ad_plugin_house_ads ORDER BY created_at DESC LIMIT 20;
```

### `ad_plugin_house_ads_categories`
How many ad plugin house ads categories records are there?
```sql
SELECT COUNT(*) AS row_count FROM ad_plugin_house_ads_categories;
```

### `ad_plugin_house_ads_categories`
Show 20 sample ad plugin house ads categories records.
```sql
SELECT ad_plugin_house_ad_id, category_id FROM ad_plugin_house_ads_categories LIMIT 20;
```

### `ad_plugin_house_ads_groups`
How many ad plugin house ads groups records are there?
```sql
SELECT COUNT(*) AS row_count FROM ad_plugin_house_ads_groups;
```

### `ad_plugin_house_ads_groups`
Show 20 sample ad plugin house ads groups records.
```sql
SELECT ad_plugin_house_ad_id, group_id FROM ad_plugin_house_ads_groups LIMIT 20;
```

### `ad_plugin_house_ads_routes`
How many ad plugin house ads routes records are there?
```sql
SELECT COUNT(*) AS row_count FROM ad_plugin_house_ads_routes;
```

### `ad_plugin_house_ads_routes`
Show 20 sample ad plugin house ads routes records.
```sql
SELECT ad_plugin_house_ad_id, route_name FROM ad_plugin_house_ads_routes LIMIT 20;
```

### `ad_plugin_impressions`
How many ad plugin impressions records are there?
```sql
SELECT COUNT(*) AS row_count FROM ad_plugin_impressions;
```

### `ad_plugin_impressions`
Show the 20 most recent ad plugin impressions records.
```sql
SELECT id, user_id, created_at, updated_at, ad_type, ad_plugin_house_ad_id FROM ad_plugin_impressions ORDER BY created_at DESC LIMIT 20;
```

