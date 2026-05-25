#!/usr/bin/env bash
set -euo pipefail

ROOT=/home/agent/work/discourse-sql-ft
PY="$ROOT/.venv/bin/python"
V2="$ROOT/training/qwen35-9b-lora-v2"
SUP_LOG="$ROOT/logs/v2-supervisor.log"
TRAIN_LOG="$V2/logs/train.log"
DONE="$V2/done"
FAILED="$V2/failed"
ADAPTER="$V2/adapter"
EVAL_SUMMARY="$ROOT/eval/execution/v2-tuned/summary.json"

mkdir -p "$ROOT/logs" "$V2/logs" "$V2/checkpoints"
cd "$ROOT"

log() {
  printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$SUP_LOG"
}

if [[ -f "$DONE" ]]; then
  log "v2 training/eval already completed; holding runit service up"
  exec sleep infinity
fi

rm -f "$FAILED"
log "runit supervised v2 run start"
log "validating dataset/train.jsonl read-only before training"
"$PY" scripts/validate_dataset_sql.py dataset/train.jsonl 2>&1 | tee -a "$SUP_LOG"

if [[ ! -f "$ADAPTER/adapter_config.json" ]]; then
  for attempt in 1 2; do
    log "starting v2 training attempt $attempt"
    printf '\n===== %s supervised attempt %s =====\n' "$(date -u +%FT%TZ)" "$attempt" >> "$TRAIN_LOG"
    if "$PY" "$V2/train_lora.py" >> "$TRAIN_LOG" 2>&1; then
      log "v2 training attempt $attempt exited 0"
    else
      rc=$?
      log "v2 training attempt $attempt failed rc=$rc"
      if [[ $attempt -ge 2 ]]; then
        echo "training failed after $attempt attempts" > "$FAILED"
        exit "$rc"
      fi
      sleep 30
      continue
    fi

    if [[ -f "$ADAPTER/adapter_config.json" ]]; then
      log "v2 adapter saved at $ADAPTER"
      break
    fi

    log "training attempt $attempt returned 0 but adapter_config.json missing"
    if [[ $attempt -ge 2 ]]; then
      echo "adapter missing after successful training" > "$FAILED"
      exit 1
    fi
  done
else
  log "v2 adapter already exists at $ADAPTER; skipping training"
fi

if [[ ! -f "$ADAPTER/adapter_config.json" ]]; then
  log "no adapter exists; cannot run v2 eval"
  echo "adapter missing" > "$FAILED"
  exit 1
fi

if [[ ! -f "$EVAL_SUMMARY" ]]; then
  log "starting v2 tuned execution eval"
  "$PY" scripts/evaluate_models.py \
    --limit 200 \
    --only tuned \
    --adapter "$ADAPTER" \
    --out-root "$ROOT/eval/execution" \
    --tuned-dir-name v2-tuned \
    --report "$ROOT/reports/execution_eval_v2.md" \
    2>&1 | tee -a "$SUP_LOG"
else
  log "v2 eval summary already exists; skipping eval"
fi

log "v2 run complete"
touch "$DONE"
exec sleep infinity
