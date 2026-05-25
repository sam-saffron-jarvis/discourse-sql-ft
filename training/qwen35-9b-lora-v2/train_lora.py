import json
from pathlib import Path
import re

import torch
from datasets import Dataset, DatasetDict
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from trl import SFTConfig, SFTTrainer

ROOT = Path('/home/agent/work/discourse-sql-ft')
MODEL = 'Qwen/Qwen3.5-9B'
OUT = ROOT / 'training/qwen35-9b-lora-v2/adapter'
CKPT_ROOT = OUT.parent / 'checkpoints'
train_path = str(ROOT / 'dataset/train.jsonl')
dev_path = str(ROOT / 'dataset/dev.jsonl')

OUT.parent.mkdir(parents=True, exist_ok=True)
(OUT.parent / 'logs').mkdir(parents=True, exist_ok=True)
CKPT_ROOT.mkdir(parents=True, exist_ok=True)

tokenizer = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token


def format_example(ex):
    return tokenizer.apply_chat_template(ex['messages'], tokenize=False, add_generation_prompt=False)


def latest_checkpoint() -> str | None:
    checkpoints = []
    if CKPT_ROOT.exists():
        for p in CKPT_ROOT.glob('checkpoint-*'):
            m = re.search(r'checkpoint-(\d+)$', p.name)
            if m:
                checkpoints.append((int(m.group(1)), p))
    return str(sorted(checkpoints)[-1][1]) if checkpoints else None


def load_chat_jsonl(path: str) -> Dataset:
    rows = []
    with open(path) as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            rows.append({'messages': row['messages'], 'family': row.get('family') or ''})
    return Dataset.from_list(rows)


ds = DatasetDict({'train': load_chat_jsonl(train_path), 'validation': load_chat_jsonl(dev_path)})

bnb = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type='nf4',
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_use_double_quant=True,
)
model = AutoModelForCausalLM.from_pretrained(
    MODEL,
    quantization_config=bnb,
    device_map='auto',
    trust_remote_code=True,
    torch_dtype=torch.bfloat16,
)
model.config.use_cache = False
model = prepare_model_for_kbit_training(model)
peft = LoraConfig(
    r=32,
    lora_alpha=64,
    lora_dropout=0.05,
    bias='none',
    task_type='CAUSAL_LM',
    target_modules=['q_proj', 'k_proj', 'v_proj', 'o_proj', 'gate_proj', 'up_proj', 'down_proj'],
)
model = get_peft_model(model, peft)
model.print_trainable_parameters()

args = SFTConfig(
    output_dir=str(CKPT_ROOT),
    num_train_epochs=3,
    per_device_train_batch_size=1,
    per_device_eval_batch_size=1,
    gradient_accumulation_steps=16,
    learning_rate=1e-4,
    bf16=True,
    logging_steps=10,
    eval_strategy='steps',
    eval_steps=50,
    save_steps=100,
    save_total_limit=2,
    report_to=[],
    optim='paged_adamw_8bit',
    warmup_ratio=0.03,
    lr_scheduler_type='cosine',
    max_length=4096,
)
trainer = SFTTrainer(
    model=model,
    args=args,
    train_dataset=ds['train'],
    eval_dataset=ds['validation'],
    formatting_func=format_example,
    processing_class=tokenizer,
)

resume = latest_checkpoint()
print('RESUME_FROM', resume, flush=True)
trainer.train(resume_from_checkpoint=resume)
OUT.mkdir(parents=True, exist_ok=True)
trainer.model.save_pretrained(str(OUT))
tokenizer.save_pretrained(str(OUT))
print('ADAPTER_SAVED', OUT, flush=True)
