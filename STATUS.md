# Discourse SQL FT Status

- Experiment: `discourse-sql-ft`
- Status: **succeeded**
- Current phase: `None`
- Updated: `2026-05-25T00:01:35Z` UTC
- Execution eval: **completed** — base exact 0/200, tuned exact 199/200
- Coverage expansion: **completed** — train rows 2500 → 3130; schema base table coverage 11/311 → 311/311
- Built-in reports/queries: **completed** — train rows 3138 → 3205; added 19 Data Explorer defaults + 48 Discourse core report examples
- Source-mined semantics: **completed** — train rows 3205 → 3241; added 36 examples from badge/tagging/topic-view/statistics/reactions/voting/custom-field/email/upload/group/auth source concepts
- Dataset formatting: **completed** — prettified SQL in `dataset/train.jsonl` and component training packs; validated all 3241 train SQL queries still execute read-only.

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

