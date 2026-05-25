# Discourse SQL Fine-tuning Experiment

An experiment in teaching a current-generation Qwen model to translate natural-language Discourse admin/forum questions into executable PostgreSQL SQL.

The experiment uses a real Discourse schema, synthetic forum data, executable canonical SQL, QLoRA fine-tuning, and execution-result evaluation against PostgreSQL.

## What is in this repo

- `scripts/` — experiment supervisor, dataset generation, coverage expansion, evaluation, and training helpers
- `config/` — experiment config, prompt, and extracted schema
- `dataset/` — synthetic train/dev/eval JSONL datasets and subsequent coverage packs
- `reports/` — generated experiment reports and evaluation summaries
- `STATUS.md` — current experiment state and headline metrics

Large/generated artifacts are intentionally not committed:

- model adapters/checkpoints (`training/`)
- Python virtualenvs (`.venv/`)
- PostgreSQL dumps/snapshots (`db/snapshots/`)
- Redis dumps (`dump.rdb`)
- runtime logs (`logs/`)

## Headline result from the first run

Held-out eval set: 200 English questions. Metric: strict execution-result equality against canonical SQL on the synthetic Discourse PostgreSQL database.

| Model | Safe SQL | Executed | Exact result match |
|---|---:|---:|---:|
| Base `Qwen/Qwen3.5-9B` | 200/200 | 154/200 | 0/200 |
| Tuned Qwen3.5-9B LoRA | 200/200 | 200/200 | 199/200 |

See `reports/execution_eval.md`.

## Dataset expansion work

After the first fine-tune, the dataset was expanded to cover:

- all 311 base tables in the real Discourse schema
- Discourse Data Explorer built-in queries
- Discourse core report concepts
- source-mined concepts from badges, tagging, topic views, reactions, voting plugins, uploads, email, groups, auth logs, and related internals
- semantic examples for high-value tables such as `topic_views`, `user_visits`, `reviewables`, `email_logs`, `ai_api_audit_logs`, and `ai_api_request_stats`

The current `dataset/train.jsonl` is synthetic and contains no production Discourse data.

## Running pieces locally

The scripts assume a local Discourse checkout and a PostgreSQL database named `discourse_sql_ft`. They were built for the original experiment container, so paths may need adjustment outside that environment.

Status:

```bash
uv run python scripts/status.py
```

Execution eval:

```bash
uv run python scripts/evaluate_models.py --limit 200 --only both
```

Coverage/report generation helpers:

```bash
uv run python scripts/improve_table_coverage.py
uv run python scripts/add_builtin_queries_reports_pack.py
uv run python scripts/add_source_mined_semantic_pack.py
```

## Safety note

This repo contains synthetic datasets, schema information, SQL, and scripts. It should not contain credentials, model weights, database dumps, or private production data.
