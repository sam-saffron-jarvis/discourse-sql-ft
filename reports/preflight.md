# Preflight Report

| Status | Item | Detail |
|---|---|---|
| ok | `root` | /home/agent/work/discourse-sql-ft |
| ok | `python` | 3.12.12 at /home/agent/work/discourse-sql-ft/.venv/bin/python3 |
| ok | `command:uv` | /usr/bin/uv |
| ok | `command:python` | /home/agent/work/discourse-sql-ft/.venv/bin/python |
| warn | `command:psql` | not found in PATH |
| warn | `command:pg_dump` | not found in PATH |
| ok | `command:git` | /usr/bin/git |
| ok | `command:curl` | /usr/bin/curl |
| ok | `command:nvidia-smi` | /usr/bin/nvidia-smi |
| ok | `gpu:0` | NVIDIA GeForce RTX 4090; 21.8/24.0 GiB free; driver 595.71.05 |
| ok | `disk space` | 1674.5 GiB free / 3602.0 GiB total at /home/agent/work/discourse-sql-ft |
| ok | `python module:yaml` | importable |
| warn | `python module:torch` | not installed yet |
| warn | `python module:transformers` | not installed yet |
| warn | `python module:peft` | not installed yet |
| warn | `python module:trl` | not installed yet |
| warn | `python module:datasets` | not installed yet |
| warn | `python module:accelerate` | not installed yet |
| warn | `python module:bitsandbytes` | not installed yet |
| ok | `jobs supervisor registration` | discourse-sql-ft-supervisor exists |
| ok | `ollama qwen models` | qwen36-a3b-q3-180224:latest      f93dbe4be007    16 GB     4 weeks ago     ; qwen36-a3b-q3-163840:latest      656c29d3d535    16 GB     4 weeks ago     ; qwen36-a3b-q3-229376:latest      a32350c4fac4    16 GB     4 weeks ago      |
| ok | `primary model` | Qwen/Qwen3.5-9B |
| ok | `fallback model` | Qwen/Qwen3.5-9B-Base |
| ok | `uv version` | uv 0.11.16 (135a36367 2026-05-21 x86_64-unknown-linux-gnu) |
| ok | `nvidia-smi version` | NVIDIA-SMI version  : 595.71.05 |

- Failures: 0
- Warnings: 9
