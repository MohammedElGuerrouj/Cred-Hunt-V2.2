#!/usr/bin/env python3
"""
LoRA Fine-Tuning Script for Credential Detection Model
Uses GPU for efficient parameter-efficient fine-tuning
"""

import json
import torch
import argparse
from pathlib import Path
from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    BitsAndBytesConfig,
    TrainingArguments,
    Trainer,
    EarlyStoppingCallback,
)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from datasets import Dataset

MAX_LEN = 768  # context + JSON answer fits comfortably
IGNORE_INDEX = -100


def load_split(jsonl_path: Path) -> Dataset:
    """Load a JSONL file with prompt/completion fields."""
    items = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            items.append({"prompt": obj["prompt"], "completion": obj["completion"]})
    print(f"   {jsonl_path.name}: {len(items)} examples")
    return Dataset.from_list(items)


def build_tokenize_fn(tokenizer):
    """Tokenize prompt+completion and mask prompt tokens from the loss."""

    eos = tokenizer.eos_token or ""

    def _tokenize(example):
        prompt = example["prompt"] + "\n"
        completion = example["completion"] + eos

        prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
        completion_ids = tokenizer(completion, add_special_tokens=False)["input_ids"]

        input_ids = (prompt_ids + completion_ids)[:MAX_LEN]
        labels = (
            [IGNORE_INDEX] * len(prompt_ids) + completion_ids
        )[:MAX_LEN]

        # Pad to MAX_LEN
        pad_id = tokenizer.pad_token_id
        attn = [1] * len(input_ids) + [0] * (MAX_LEN - len(input_ids))
        input_ids = input_ids + [pad_id] * (MAX_LEN - len(input_ids))
        labels = labels + [IGNORE_INDEX] * (MAX_LEN - len(labels))

        return {
            "input_ids": input_ids,
            "attention_mask": attn,
            "labels": labels,
        }

    return _tokenize

def setup_lora_config():
    """Configure LoRA parameters for efficient fine-tuning"""

    config = LoraConfig(
        r=16,
        lora_alpha=32,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )
    print("⚙️  LoRA Configuration:")
    print(f"   Rank: {config.r}, Alpha: {config.lora_alpha}")
    print(f"   Target modules: {config.target_modules}")
    return config

def main():
    parser = argparse.ArgumentParser(description="LoRA Fine-Tune Credential Detection Model")
    parser.add_argument("--model", default="qwen2.5-coder:3b", help="Base model name")
    parser.add_argument("--epochs", type=int, default=3, help="Number of training epochs")
    parser.add_argument("--batch-size", type=int, default=4, help="Batch size")
    parser.add_argument("--learning-rate", type=float, default=5e-4, help="Learning rate")
    parser.add_argument("--gpu", action="store_true", help="Use GPU for training")
    parser.add_argument("--output-dir", default="./lora-credentials-detector", help="Output directory")
    parser.add_argument("--target", choices=["binary", "multiclass", "both"], default="both", help="Training target contract metadata")
    parser.add_argument("--train", default="data/training_data_binary.jsonl", help="Training JSONL path")
    parser.add_argument("--val", default="data/val_data_binary.jsonl", help="Validation JSONL path")
    parser.add_argument("--load-4bit", action="store_true",
                        help="QLoRA: load the base model in 4-bit (nf4). Required to fit a 3B model on <=8GB VRAM. Implies --gpu.")

    args = parser.parse_args()

    print("\n" + "="*70)
    print("🎯 LORA FINE-TUNING FOR CREDENTIAL DETECTION")
    print("="*70)
    print(f"Model: {args.model}")
    print(f"Epochs: {args.epochs}")
    print(f"Batch size: {args.batch_size}")
    print(f"Learning rate: {args.learning_rate}")
    print(f"GPU enabled: {args.gpu}")
    print(f"Output dir: {args.output_dir}")
    print(f"Target: {args.target}")
    print()

    # Check for training data
    train_file = Path(args.train)
    val_file = Path(args.val)
    if not train_file.exists() or not val_file.exists():
        print("❌ Training/validation data not found!")
        print("   Run: python scripts/process_synthetic_training_data.py")
        return

    # Check GPU availability
    if args.gpu:
        if not torch.cuda.is_available():
            print("❌ GPU requested but not available!")
            print("   Install CUDA or run without --gpu flag")
            return
        device = torch.device("cuda")
        print(f"✅ GPU available: {torch.cuda.get_device_name()}")
    else:
        device = torch.device("cpu")
        print("⚠️  Using CPU (training will be slow)")

    try:
        # Load tokenizer and model
        print("\n🔄 Loading model and tokenizer...")
        model_name = args.model

        # For Ollama models, we need to use the HuggingFace equivalent
        if "qwen2.5-coder:3b" in model_name:
            hf_model_name = "Qwen/Qwen2.5-Coder-3B-Instruct"
        elif "qwen2.5-coder:1.5b" in model_name:
            hf_model_name = "Qwen/Qwen2.5-Coder-1.5B-Instruct"
        elif "qwen2.5" in model_name:
            hf_model_name = "Qwen/Qwen2.5-1.5B"
        else:
            hf_model_name = model_name

        tokenizer = AutoTokenizer.from_pretrained(hf_model_name, trust_remote_code=True)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        quant_config = None
        if args.load_4bit:
            if not args.gpu:
                print("❌ --load-4bit requires --gpu")
                return
            quant_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True,
            )
            print("🧮 QLoRA: loading base model in 4-bit (nf4, double-quant)")

        model = AutoModelForCausalLM.from_pretrained(
            hf_model_name,
            quantization_config=quant_config,
            torch_dtype=torch.float16 if args.gpu else torch.float32,
            device_map="auto" if args.gpu else None,
            trust_remote_code=True
        )

        # Apply LoRA. The QLoRA path prepares the quantized model for training
        # first (casts norms to fp32, enables input grads, gradient checkpointing).
        lora_config = setup_lora_config()
        if args.load_4bit:
            model = prepare_model_for_kbit_training(model)
        model = get_peft_model(model, lora_config)
        model.print_trainable_parameters()

        # Load split datasets
        print("\n📖 Loading split datasets...")
        train_raw = load_split(train_file)
        eval_raw = load_split(val_file)

        # Tokenize with prompt-token masking (loss only on JSON answer)
        print("\n🔄 Tokenizing datasets...")
        tok = build_tokenize_fn(tokenizer)
        tokenized_train = train_raw.map(tok, remove_columns=train_raw.column_names)
        tokenized_eval = eval_raw.map(tok, remove_columns=eval_raw.column_names)

        # Training arguments
        training_args = TrainingArguments(
            output_dir=args.output_dir,
            num_train_epochs=args.epochs,
            per_device_train_batch_size=args.batch_size,
            per_device_eval_batch_size=args.batch_size,
            gradient_accumulation_steps=2,
            learning_rate=args.learning_rate,
            weight_decay=0.01,
            warmup_ratio=0.05,
            logging_steps=10,
            save_steps=200,
            eval_steps=200,
            eval_strategy="steps",
            save_strategy="steps",
            save_total_limit=2,
            load_best_model_at_end=True,
            metric_for_best_model="eval_loss",
            greater_is_better=False,
            fp16=args.gpu,
            gradient_checkpointing=True,
            gradient_checkpointing_kwargs={"use_reentrant": False},
            optim="paged_adamw_8bit" if args.load_4bit else "adamw_torch",
            dataloader_num_workers=0,
            report_to="none",
        )

        trainer = Trainer(
            model=model,
            args=training_args,
            train_dataset=tokenized_train,
            eval_dataset=tokenized_eval,
            callbacks=[EarlyStoppingCallback(early_stopping_patience=3)],
        )

        # Train!
        print("\n🚀 Starting LoRA fine-tuning...")
        print("   This may take 1-2 hours depending on your GPU...")
        trainer.train()

        # Save the fine-tuned model
        print(f"\n💾 Saving fine-tuned model to {args.output_dir}...")
        trainer.save_model(args.output_dir)
        tokenizer.save_pretrained(args.output_dir)

        # Save LoRA adapter specifically
        model.save_pretrained(args.output_dir)

        print("\n✅ Fine-tuning complete!")
        print(f"   Model saved to: {args.output_dir}")
        print("\n📋 Next steps:")
        print("   1. Create Ollama model: ollama create credentials-detector-lora -f Modelfile.credentials-detector")
        print("   2. Test model: python scripts/test_trained_model.py")
        print("   3. Evaluate: python scripts/evaluate_model_performance.py")

    except Exception as e:
        print(f"\n❌ Error during fine-tuning: {e}")
        print("\n🔧 Troubleshooting:")
        print("   1. Check GPU memory: Reduce batch_size if needed")
        print("   2. Check CUDA installation: nvcc --version")
        print("   3. Try CPU training: Remove --gpu flag")
        return

if __name__ == "__main__":
    main()