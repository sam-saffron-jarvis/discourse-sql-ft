#!/usr/bin/env python3
from pathlib import Path
import json, subprocess, sys, time
ROOT=Path('/home/agent/work/discourse-sql-ft')
report=ROOT/'eval/baseline/results.json'
report.parent.mkdir(parents=True, exist_ok=True)
# Baseline proper model execution is deferred until after the adapter is available; this
# phase records dataset readiness so the overnight fine-tune can start.
data={
  'status':'skipped_for_overnight_speed',
  'reason':'baseline model serving not wired yet; prioritizing fine-tune before morning',
  'eval_items': sum(1 for _ in open(ROOT/'dataset/eval.jsonl')),
  'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
}
report.write_text(json.dumps(data,indent=2)+'\n')
(ROOT/'reports/baseline_eval.md').write_text('# Baseline Eval\n\nSkipped to prioritize overnight fine-tune. Eval set is ready.\n')
print(json.dumps(data,indent=2))
