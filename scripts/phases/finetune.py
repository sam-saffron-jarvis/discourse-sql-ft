#!/usr/bin/env python3
from __future__ import annotations
import importlib.util, os, subprocess, sys, textwrap, time
from pathlib import Path

ROOT=Path('/home/agent/work/discourse-sql-ft')
MODEL='Qwen/Qwen3.5-9B'
OUT=ROOT/'training/qwen35-9b-lora/adapter'
LOG=ROOT/'training/qwen35-9b-lora/logs/train.log'
SCRIPT=ROOT/'training/qwen35-9b-lora/train_lora.py'

def run(cmd, timeout=None):
    print('+',' '.join(map(str,cmd)), flush=True)
    return subprocess.run(cmd, cwd=ROOT, text=True, timeout=timeout, check=True)

needed=['torch','transformers','datasets','peft','trl','accelerate','bitsandbytes']
missing=[m for m in needed if importlib.util.find_spec(m) is None]
if missing:
    run(['uv','pip','install','--upgrade','torch','transformers','datasets','peft','trl','accelerate','bitsandbytes'], timeout=7200)

SCRIPT.parent.mkdir(parents=True, exist_ok=True)
SCRIPT.write_text(textwrap.dedent(f'''
from pathlib import Path
import torch
from datasets import load_dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, TrainingArguments
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from trl import SFTTrainer, SFTConfig

ROOT=Path('/home/agent/work/discourse-sql-ft')
MODEL='{MODEL}'
OUT=Path('{OUT}')
train_path=str(ROOT/'dataset/train.jsonl')
dev_path=str(ROOT/'dataset/dev.jsonl')

tokenizer=AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

def format_example(ex):
    return tokenizer.apply_chat_template(ex['messages'], tokenize=False, add_generation_prompt=False)

ds=load_dataset('json', data_files={{'train':train_path,'validation':dev_path}})

bnb=BitsAndBytesConfig(load_in_4bit=True,bnb_4bit_quant_type='nf4',bnb_4bit_compute_dtype=torch.bfloat16,bnb_4bit_use_double_quant=True)
model=AutoModelForCausalLM.from_pretrained(MODEL, quantization_config=bnb, device_map='auto', trust_remote_code=True, torch_dtype=torch.bfloat16)
model.config.use_cache=False
model=prepare_model_for_kbit_training(model)
peft=LoraConfig(r=32,lora_alpha=64,lora_dropout=0.05,bias='none',task_type='CAUSAL_LM',target_modules=['q_proj','k_proj','v_proj','o_proj','gate_proj','up_proj','down_proj'])
model=get_peft_model(model, peft)
model.print_trainable_parameters()
args=SFTConfig(output_dir=str(OUT.parent/'checkpoints'), num_train_epochs=3, per_device_train_batch_size=1, per_device_eval_batch_size=1, gradient_accumulation_steps=16, learning_rate=1e-4, bf16=True, logging_steps=10, eval_strategy='steps', eval_steps=50, save_steps=100, save_total_limit=2, report_to=[], optim='paged_adamw_8bit', warmup_ratio=0.03, lr_scheduler_type='cosine', max_length=4096)
trainer=SFTTrainer(model=model, args=args, train_dataset=ds['train'], eval_dataset=ds['validation'], formatting_func=format_example, processing_class=tokenizer)

import re
ckpt_root = OUT.parent / 'checkpoints'
checkpoints = []
if ckpt_root.exists():
    for p in ckpt_root.glob('checkpoint-*'):
        m = re.search(r'checkpoint-(\d+)$', p.name)
        if m:
            checkpoints.append((int(m.group(1)), p))
resume = str(sorted(checkpoints)[-1][1]) if checkpoints else None
print('RESUME_FROM', resume)
trainer.train(resume_from_checkpoint=resume)
OUT.mkdir(parents=True, exist_ok=True)
trainer.model.save_pretrained(str(OUT))
tokenizer.save_pretrained(str(OUT))
print('ADAPTER_SAVED', OUT)
'''))
LOG.parent.mkdir(parents=True, exist_ok=True)
with LOG.open('a') as f:
    f.write(f"===== fine-tune start {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} =====\n")
    proc=subprocess.run([sys.executable,str(SCRIPT)], cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, text=True, timeout=40000)
    f.write(f"===== fine-tune end exit={proc.returncode} {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} =====\n")
if proc.returncode!=0:
    raise SystemExit(proc.returncode)
(ROOT/'reports/finetune.md').write_text(f'# Fine-tune\n\nAdapter saved to `{OUT}`.\n\nLog: `{LOG}`\n')
print(f'Adapter saved to {OUT}')
