#!/usr/bin/env python3
from pathlib import Path
import json, time
ROOT=Path('/home/agent/work/discourse-sql-ft')
adapter=ROOT/'training/qwen35-9b-lora/adapter'
data={'status':'adapter_exists' if adapter.exists() else 'missing_adapter','adapter':str(adapter),'eval_items':sum(1 for _ in open(ROOT/'dataset/eval.jsonl')),'created_at':time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
(ROOT/'eval/tuned').mkdir(parents=True, exist_ok=True)
(ROOT/'eval/tuned/results.json').write_text(json.dumps(data,indent=2)+'\n')
(ROOT/'reports/final_eval.md').write_text('# Final Eval\n\nAdapter existence check complete. Full execution eval still needs model serving wrapper.\n\n```json\n'+json.dumps(data,indent=2)+'\n```\n')
print(json.dumps(data,indent=2))
if data['status']!='adapter_exists':
    raise SystemExit(1)
