#!/usr/bin/env python3
"""
Train LoRA adapters for Nano-Bio Evaluator agents on Qwen3-VL-8B.
Uses HuggingFace PEFT + TRL for reliable training.
"""

import os, json, torch, logging
from pathlib import Path
from datasets import Dataset
from peft import LoraConfig, get_peft_model, TaskType, PeftModel
from transformers import (
    Qwen3VLForConditionalGeneration, AutoProcessor,
    TrainingArguments, Trainer, DataCollatorForLanguageModeling,
)
from trl import SFTTrainer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("train-lora")

PROJECT_ROOT = os.environ.get("CU_AGENT_ROOT", "E:/Cu-agent")
MODEL_PATH = "E:/models/qwen/Qwen3-VL-8B-Instruct"
DATA_DIR = Path(PROJECT_ROOT) / "data" / "training"
OUTPUT_DIR = Path(PROJECT_ROOT) / "models" / "lora"

TRAINING_CONFIG = {
    "ea":  {"rank": 32, "epochs": 3, "lr": 5e-5, "batch": 4},
    "apa": {"rank": 64, "epochs": 5, "lr": 5e-5, "batch": 4},
    "epa": {"rank": 64, "epochs": 5, "lr": 5e-5, "batch": 4},
    "bsa": {"rank": 64, "epochs": 5, "lr": 5e-5, "batch": 4},
    "mma": {"rank": 64, "epochs": 5, "lr": 5e-5, "batch": 4},
    "toa": {"rank": 32, "epochs": 1, "lr": 5e-5, "batch": 4},
    "ca":  {"rank": 32, "epochs": 3, "lr": 5e-5, "batch": 4},
}


def load_training_data(agent_name: str) -> Dataset:
    """Load and format training data for an agent."""
    data_path = DATA_DIR / f"{agent_name}_training_data.jsonl"
    if not data_path.exists():
        raise FileNotFoundError(f"No training data: {data_path}")

    texts = []
    with open(data_path, "r", encoding="utf-8") as f:
        for line in f:
            entry = json.loads(line)
            text = f"### Instruction:\n{entry['instruction']}\n\n### Input:\n{entry['input']}\n\n### Response:\n{entry.get('output', '')}"
            texts.append({"text": text})

    dataset = Dataset.from_list(texts)
    logger.info(f"Loaded {len(dataset)} training samples for {agent_name}")
    return dataset


def train_agent(agent_name: str):
    """Fine-tune a single agent's LoRA adapter."""
    config = TRAINING_CONFIG[agent_name]
    logger.info(f"\n{'='*60}")
    logger.info(f"Training {agent_name.upper()} LoRA adapter")
    logger.info(f"Rank={config['rank']}, Epochs={config['epochs']}, LR={config['lr']}")
    logger.info(f"{'='*60}")

    # Load dataset
    dataset = load_training_data(agent_name)
    if len(dataset) < 10:
        logger.warning(f"Only {len(dataset)} samples — skipping {agent_name}")
        return

    # Load model in 4-bit for training efficiency
    from transformers import BitsAndBytesConfig
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
    )

    model = Qwen3VLForConditionalGeneration.from_pretrained(
        MODEL_PATH,
        quantization_config=bnb_config,
        device_map="auto",
        torch_dtype=torch.bfloat16,
    )

    # Enable gradient checkpointing for memory efficiency
    model.gradient_checkpointing_enable()
    model.config.use_cache = False

    # LoRA config
    lora_config = LoraConfig(
        r=config["rank"],
        lora_alpha=config["rank"] * 2,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
    )

    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # Processor for text formatting
    processor = AutoProcessor.from_pretrained(MODEL_PATH)

    def tokenize(example):
        return processor(
            text=example["text"],
            truncation=True,
            max_length=512,
            padding="max_length",
        )

    tokenized = dataset.map(tokenize, batched=True, remove_columns=["text"])

    # Training arguments
    output_dir = OUTPUT_DIR / agent_name
    training_args = TrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=config["epochs"],
        per_device_train_batch_size=config["batch"],
        gradient_accumulation_steps=2,
        learning_rate=config["lr"],
        warmup_ratio=0.03,
        weight_decay=0.01,
        logging_steps=10,
        save_strategy="epoch",
        bf16=True,
        report_to="none",
        dataloader_num_workers=0,
    )

    # Trainer
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized,
        data_collator=DataCollatorForLanguageModeling(
            tokenizer=processor.tokenizer, mlm=False
        ),
    )

    # Train
    trainer.train()

    # Save adapter
    model.save_pretrained(output_dir)
    processor.tokenizer.save_pretrained(output_dir)
    logger.info(f"Saved LoRA adapter to {output_dir}")

    # Cleanup
    del model
    torch.cuda.empty_cache()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        agent = sys.argv[1]
        if agent in TRAINING_CONFIG:
            train_agent(agent)
        elif agent == "all":
            for a in TRAINING_CONFIG:
                train_agent(a)
        else:
            print(f"Unknown agent: {agent}. Choices: {list(TRAINING_CONFIG.keys())} + all")
    else:
        print("Usage: python train_agent_lora.py [agent_name|all]")
        print(f"Agents: {list(TRAINING_CONFIG.keys())}")
