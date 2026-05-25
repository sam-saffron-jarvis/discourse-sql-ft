# Discourse SQL FT Status

- Experiment: `discourse-sql-ft`
- Status: **succeeded**
- Current phase: `None`
- Updated: `2026-05-25T07:22:15Z` UTC
- Execution eval: **completed** — base exact 0/200, tuned exact 199/200
- Coverage expansion: **completed** — train rows 2500 → 3130; schema base table coverage 11/311 → 311/311
- Built-in reports/queries: **completed** — train rows 3138 → 3205; added 19 Data Explorer defaults + 48 Discourse core report examples
- Source-mined semantics: **completed** — train rows 3205 → 3241; added 36 examples from badge/tagging/topic-view/statistics/reactions/voting/custom-field/email/upload/group/auth source concepts
- Action type semantics: **completed** — train rows 3241 → 3269; added 28 examples for `post_actions`, `post_action_types`, `flags`, and `user_actions` mappings from Discourse source.
- Topic view stats semantics: **completed** — train rows 3269 → 3281; added 12 examples for `topic_view_stats` page views per topic, anonymous/logged-in splits, daily topic stats, category filtering, and source-style report shape.
- Dataset formatting: **completed** — prettified SQL consistently across tracked dataset JSONL files and the new topic-view-stats pack; latest full validation: 3281 train SQL queries, 0 failures.
- V2 fine-tune: **running** — pre-training read-only validation passed (3281/3281, 0 failures). A runit-supervised service `discourse-sql-ft-v2` is training `Qwen/Qwen3.5-9B` into `training/qwen35-9b-lora-v2/adapter` without overwriting the v1 adapter; it will retry/resume from v2 checkpoints and then run tuned execution eval under `eval/execution/v2-tuned`. Logs: `logs/v2-supervisor.log` and `training/qwen35-9b-lora-v2/logs/train.log`.

| Phase | Status | Attempts | Started | Finished | Error |
|---|---:|---:|---|---|---|
| `preflight` | **succeeded** | 1 | 2026-05-24T10:50:41Z | 2026-05-24T10:50:41Z |  |
| `build_forum` | **succeeded** | 8 | 2026-05-24T11:23:34Z | 2026-05-24T13:21:11Z |  |
| `generate_dataset` | **succeeded** | 2 | 2026-05-24T13:23:53Z | 2026-05-24T13:23:57Z |  |
| `baseline_eval` | **succeeded** | 1 | 2026-05-24T13:23:57Z | 2026-05-24T13:23:57Z |  |
| `finetune` | **succeeded** | 3 | 2026-05-24T23:01:10Z | 2026-05-24T23:28:19Z |  |
| `final_eval` | **succeeded** | 1 | 2026-05-24T23:28:19Z | 2026-05-24T23:28:19Z |  |

## Logs

- Supervisor: `logs/supervisor.log`
- Phase logs: `logs/<phase>.log`

