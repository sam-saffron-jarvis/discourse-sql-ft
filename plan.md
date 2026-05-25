# Plan

Fine-tune `Qwen/Qwen3.5-9B` using QLoRA on validated synthetic Discourse PostgreSQL question-to-SQL examples.

Primary metric: held-out exact execution-result match against canonical SQL on a frozen synthetic forum DB snapshot.

The supervisor runs phases idempotently and records progress in `state/supervisor.json` and `STATUS.md`.
