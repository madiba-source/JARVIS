# Local Model Evaluation

Phase: 02, local-only capability and resource safety validation
Baseline date: 2026-09-17

This document records only local measurements and public model metadata. No prompts, reports, or system information are uploaded.

## Hardware

- CPU: Intel Core i5-8350U, 4 cores / 8 threads
- RAM: 15 GiB; 12 GiB swap
- GPU: Intel UHD Graphics 620; no CUDA/NVIDIA runtime detected
- Disk before model testing: 197 GiB available on `/`
- Current desktop load: approximately 2.86 load average at inspection; active browser and VS Code processes were present
- Thermal telemetry: available through `/sys/class/thermal`; observed zones ranged from 20 C to 60 C at baseline. Zone labels are generic, so this is not a validated CPU package temperature.

## Candidate selection

At most two candidates are selected for controlled testing. The first candidate is pulled only after recording disk headroom. Ollama manages weights outside this repository.

| Tag | Classification | Parameters | Quantization | Approx. size | Context | License | Tool/structured output |
| --- | --- | ---: | --- | ---: | ---: | --- | --- |
| `qwen2.5:1.5b` | open-source/open-weight | 1.54B | Q4_K_M | 986 MB | 32K advertised | Apache 2.0 | Model/tool behavior requires local verification; Ollama supports JSON schema output and simulated tools |
| `qwen3:1.7b` | open-source/open-weight | 2.03B | Q4_K_M | 1.4 GB | 40K advertised | Apache 2.0 | Qwen documents tool use; Ollama supports JSON schema output and simulated tools |

These are model-page estimates, not measured runtime memory. Advertised context is not the Phase 02 operating context; benchmark prompts are short and output is capped at 128 generated tokens.

Sources:

- [Ollama Qwen3 tags](https://ollama.com/library/qwen3/tags)
- [Ollama Qwen3 1.7B](https://ollama.com/library/qwen3:1.7b)
- [Ollama Qwen2.5 tags](https://ollama.com/library/qwen2.5/tags)
- [Ollama Qwen2.5 1.5B](https://ollama.com/library/qwen2.5:1.5b)
- [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs)
- [Ollama tool calling](https://docs.ollama.com/capabilities/tool-calling)
- [Qwen3 repository and license](https://github.com/QwenLM/Qwen3)
- [Qwen2.5 announcement and license](https://qwenlm.github.io/blog/qwen2.5/)

## Safety controls

- One model is benchmarked per command.
- Five fixed prompts maximum, plus one structured-output request and one simulated-tool request.
- Generation is capped at 128 tokens and temperature is zero.
- HTTP timeout is 120 seconds with a 5-second connection timeout.
- The benchmark uses only `127.0.0.1:11434` and never gives the model real tools.
- Returned tool calls are recorded but never executed.
- Benchmark output defaults to `/tmp` and is never committed.
- No model files are stored in the repository.

## Benchmark results

Results are added below only after the local benchmark completes. Each run records disk/resource snapshots before and after inference, latency, evaluation count, token rate when Ollama provides it, and thermal-zone readings when available.

### `qwen2.5:1.5b`

- Status: benchmarked successfully
- Ollama tag/digest: `qwen2.5:1.5b` / `65ec06548149`
- Download/model size: 986 MB
- Disk: 197 GiB available before pull; 196 GiB available after pull; approximately 1 GiB filesystem change
- Benchmark: five fixed prompts, plus structured output and simulated tool-call checks
- First response latency: 0.641 to 1.179 seconds across the five prompts
- Total prompt latency: 1.145 to 11.935 seconds
- Generated rate: 11.67 to 14.43 tokens/sec
- Aggregate CPU during run: 79.95%
- Memory: 3,295 MiB available before; 3,409 MiB available after this rerun
- Swap: 176 MiB before and after this rerun
- Thermal telemetry: generic thermal zones maximum 55.05 C before and 63.05 C after; CPU package temperature is not identified
- Structured output: valid Pydantic response
- Simulated tool call: one `fake_open_application` request; not executed
- Stability: no crash or timeout

### `qwen3:1.7b`

- Status: documented but not downloaded
- Reason: the smaller candidate met the Phase 02 capability checks, while the host had approximately 3.2 GiB available RAM under an active desktop workload. The conservative policy avoids adding a second resident model without a demonstrated need.

## Offline behavior

The Phase 02 provider state model represents `online`, `offline`, `unavailable`, and `timeout` explicitly. JARVIS startup and unit tests do not call the internet or cloud APIs. Ollama itself is a local endpoint; loss of external internet does not affect its local API.

## Cleanup

Remove a benchmark model from Ollama storage with the exact tag after confirming it is no longer needed:

```bash
ollama rm qwen2.5:1.5b
ollama rm qwen3:1.7b
```

Do not remove a model that has been selected for deployment without first recording the decision and confirming no local workflow depends on it.

## Decision

Deployment candidate: `qwen2.5:1.5b`. The measured run completed without crash or timeout, produced valid structured output, produced a simulated tool request, and ran entirely through the local Ollama endpoint. It is selected for the initial local capability baseline; `qwen3:1.7b` remains an optional later comparison, not a required dependency.
