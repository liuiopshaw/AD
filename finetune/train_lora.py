#!/usr/bin/env python3
"""LoRA fine-tuning pipeline for 7 nano-bio evaluator agents on LLaVA-1.6-13B."""

import subprocess
import yaml
from pathlib import Path

AGENTS = ["ea", "apa", "epa", "bsa", "mma", "toa", "ca"]

TRAINING_PARAMS = {
    "ea":  {"rank": 32, "epochs": 3, "lr": 5e-5, "seq_len": 512},
    "apa": {"rank": 64, "epochs": 5, "lr": 5e-5, "seq_len": 512},
    "epa": {"rank": 64, "epochs": 5, "lr": 5e-5, "seq_len": 512},
    "bsa": {"rank": 64, "epochs": 5, "lr": 5e-5, "seq_len": 512},
    "mma": {"rank": 64, "epochs": 5, "lr": 5e-5, "seq_len": 512},
    "toa": {"rank": 32, "epochs": 1, "lr": 5e-5, "seq_len": 128},
    "ca":  {"rank": 32, "epochs": 3, "lr": 5e-5, "seq_len": 512},
}


def generate_config(agent_name: str, params: dict):
    config = {
        "model_name_or_path": "liuhaotian/llava-v1.6-vicuna-13b",
        "quantization_bit": 4,
        "lora_rank": params["rank"],
        "lora_alpha": params["rank"] * 2,
        "lora_target": "q_proj,k_proj,v_proj,o_proj",
        "lora_dropout": 0.05,
        "stage": "sft",
        "dataset": f"{agent_name}_training_data",
        "template": "vicuna",
        "finetuning_type": "lora",
        "learning_rate": params["lr"],
        "num_train_epochs": params["epochs"],
        "per_device_train_batch_size": 4,
        "gradient_accumulation_steps": 2,
        "max_seq_length": params["seq_len"],
        "warmup_ratio": 0.03,
        "weight_decay": 0.01,
        "bf16": True,
        "output_dir": f"./models/lora/{agent_name}"
    }

    config_dir = Path("finetune/configs")
    config_dir.mkdir(parents=True, exist_ok=True)
    with open(config_dir / f"{agent_name}_config.yaml", "w") as f:
        yaml.dump(config, f, default_flow_style=False)
    return config_dir / f"{agent_name}_config.yaml"


def train_agent(agent_name: str):
    print(f"\n{'='*60}")
    print(f"Training {agent_name.upper()} LoRA adapter...")
    print(f"{'='*60}")

    params = TRAINING_PARAMS[agent_name]
    config_path = generate_config(agent_name, params)
    print(f"Config: {config_path}")
    print(f"Rank={params['rank']}, Epochs={params['epochs']}, LR={params['lr']}")

    # LLaMA-Factory CLI training command
    cmd = [
        "llamafactory-cli", "train",
        "--config", str(config_path)
    ]
    print(f"Command: {' '.join(cmd)}")

    try:
        subprocess.run(cmd, check=True)
        print(f"✓ {agent_name} adapter saved to ./models/lora/{agent_name}/")
    except subprocess.CalledProcessError as e:
        print(f"✗ {agent_name} training failed: {e}")
    except FileNotFoundError:
        print(f"✗ llamafactory-cli not found. Install with: pip install llamafactory")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        agent = sys.argv[1]
        if agent in AGENTS:
            train_agent(agent)
        else:
            print(f"Unknown agent: {agent}. Choices: {AGENTS}")
    else:
        for agent in AGENTS:
            train_agent(agent)
