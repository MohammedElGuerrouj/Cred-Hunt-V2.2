# Model Selection

This project should benchmark small local models that are strong at structured JSON output, code/config understanding, classification, and low-latency local inference.

The selected models should run through Ollama first. LoRA fine-tuning can remain focused on Qwen-compatible Hugging Face models until the training scripts support other model families cleanly.

## Primary 3-Model Benchmark

The trio is deliberately family-diverse: same parameter class (~2-3B), three different training recipes. This isolates "which family generalizes to secret detection" rather than re-confirming intra-family scaling.

| Role | Model | Why |
|---|---|---|
| Code/config specialist | `qwen2.5-coder:3b` | Strongest match for credentials in source code, config files, env files, CI files |
| Agentic / JSON-disciplined | `granite3.3:2b` | IBM model designed for classification, extraction, code tasks, long context, controllable thinking |
| General-purpose challenger | `llama3.2:3b` | Meta instruction-tuned baseline from a different family; tests whether code-tuning is actually paying off |

Pull commands:

```bash
ollama pull qwen2.5-coder:3b
ollama pull granite3.3:2b
ollama pull llama3.2:3b
```

`qwen2.5:1.5b` was retired from the primary tier: it is a smaller same-family sibling of `qwen2.5-coder:3b`, so it teaches intra-family scaling but not architectural lessons.

## Extended 5-Model Benchmark

Add these if time and compute allow:

| Model | Why |
|---|---|
| `phi4-mini:3.8b` | Strong compact reasoning and function-calling candidate |
| `deepseek-r1:1.5b` | Dedicated reasoning model; useful for reasoning-strategy experiments |

Pull commands:

```bash
ollama pull phi4-mini:3.8b
ollama pull deepseek-r1:1.5b
```

## Edge Baseline

| Model | Why |
|---|---|
| `smollm2:1.7b` | Useful to test how small the project can go while retaining acceptable JSON classification |

```bash
ollama pull smollm2:1.7b
```

## Upper-Bound Models

Use these only if the machine can handle the memory and latency:

```bash
ollama pull qwen2.5:7b
ollama pull qwen2.5-coder:7b
ollama pull granite3.3:8b
```

These are not the main SLM target, but they provide a useful upper bound for expected quality.

## Selection Criteria

| Criterion | Why it matters |
|---|---|
| JSON validity | The pipeline depends on parseable structured output |
| Binary F1 | Main target is `is_credentials` |
| False-positive reduction | The project aims to avoid noisy credential reports |
| Hard-negative recall | Model must reject real-looking strings in non-credential contexts |
| Latency | Agentic reasoning can multiply inference calls |
| Context handling | The model reads surrounding code/config/docs context |
| Tool/reasoning compatibility | ReAct and self-consistency need stable instruction following |
| Local availability | Ollama support keeps benchmark reproducible |

## Recommended First Run

Start with:

```text
qwen2.5-coder:3b
granite3.3:2b
llama3.2:3b
```

Run each with:

```text
direct_json
few_shot
self_consistency
```

Then add `cot_distilled` and `react_triage` only after the dataset, JSON contract, and basic benchmark runner are stable.

## Expected Hypothesis

The likely practical winner before LoRA is:

```text
qwen2.5-coder:3b + few_shot + self_consistency on borderline cases
```

The likely production winner after LoRA is:

```text
credentials-detector-lora + few_shot or direct_json
```

## Notes

- `deepseek-r1:1.5b` is useful for reasoning experiments, but may produce longer reasoning-style outputs. Use strict JSON prompts and measure JSON validity carefully.
- `granite3.3:2b` is attractive for agentic AI because it is designed for classification, extraction, code tasks, long context, and controllable thinking.
- `qwen2.5-coder:3b` is the strongest match for source-code and config-file credential contexts.
