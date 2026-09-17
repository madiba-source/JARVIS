#!/usr/bin/env python3
"""Run a finite, local-only Ollama model benchmark.

The benchmark sends prompts to the local Ollama API only. It never exposes OS
tools to the model and never executes returned tool calls.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.model.validation import StructuredModelResponse
from app.resources.monitor import ResourceSnapshot, capture_snapshot

OLLAMA_DEFAULT = "http://127.0.0.1:11434"
PROMPTS = (
    "Respond with exactly: JARVIS TEST OK",
    "Return valid JSON with fields task, priority, offline_capable. Use task='test', priority='normal', offline_capable=true.",
    "Explain in three short sentences what a desktop assistant does.",
    "Given the user request 'open Firefox', describe the tool call you would propose. Do not execute anything.",
    "Given the user request 'delete all files in my home directory', explain why this should require authorization. Do not execute anything.",
)
STRUCTURED_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string"},
        "action": {"type": "string"},
        "requires_confirmation": {"type": "boolean"},
        "risk_level": {"type": "string", "enum": [f"L{i}" for i in range(6)]},
    },
    "required": ["intent", "action", "requires_confirmation", "risk_level"],
}
FAKE_TOOLS = [
    {"type": "function", "function": {"name": "fake_open_application", "description": "Simulate opening an application", "parameters": {"type": "object", "properties": {"app_name": {"type": "string"}}, "required": ["app_name"]}}},
    {"type": "function", "function": {"name": "fake_search_files", "description": "Simulate searching files", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "fake_create_note", "description": "Simulate creating a note", "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "body": {"type": "string"}}, "required": ["title", "body"]}}},
]


class BenchmarkConfig(BaseModel):
    """Finite benchmark controls validated before any model request."""

    max_prompts: int = Field(default=len(PROMPTS), ge=1, le=len(PROMPTS))
    request_timeout_seconds: float = Field(default=120, gt=0, le=120)
    max_output_tokens: int = Field(default=128, ge=1, le=128)


def _snapshot_dict(snapshot: ResourceSnapshot) -> dict[str, Any]:
    return snapshot.model_dump(mode="json")


def _cpu_times() -> tuple[int, int] | None:
    try:
        fields = Path("/proc/stat").read_text().splitlines()[0].split()
        values = [int(value) for value in fields[1:]]
        return sum(values), values[3]
    except (FileNotFoundError, IndexError, ValueError):
        return None


def _cpu_percent(before: tuple[int, int] | None, after: tuple[int, int] | None) -> float | None:
    if before is None or after is None:
        return None
    total_delta = after[0] - before[0]
    idle_delta = after[1] - before[1]
    return round((1 - idle_delta / total_delta) * 100, 2) if total_delta > 0 else None


def _model_names(client: httpx.Client, base_url: str) -> list[str]:
    response = client.get(f"{base_url}/api/tags")
    response.raise_for_status()
    return [item["name"] for item in response.json().get("models", [])]


def validate_model_installed(model: str, installed_models: list[str]) -> None:
    if model not in installed_models:
        raise ValueError(f"model is not installed: {model}")


def _generate(client: httpx.Client, base_url: str, model: str, prompt: str, **options: Any) -> dict[str, Any]:
    started = time.perf_counter()
    first_response_seconds: float | None = None
    response_text = ""
    final: dict[str, Any] = {}
    payload = {"model": model, "prompt": prompt, "stream": True, "options": {"temperature": 0, "num_predict": 128}, **options}
    with client.stream("POST", f"{base_url}/api/generate", json=payload) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line:
                continue
            event = json.loads(line)
            if first_response_seconds is None and event.get("response"):
                first_response_seconds = time.perf_counter() - started
            response_text += event.get("response", "")
            if event.get("done"):
                final = event
    return {
        "response": response_text,
        "first_response_seconds": first_response_seconds,
        "total_seconds": time.perf_counter() - started,
        "eval_count": final.get("eval_count"),
        "eval_duration_ns": final.get("eval_duration"),
    }


def _structured_test(client: httpx.Client, base_url: str, model: str) -> dict[str, Any]:
    result = _generate(client, base_url, model, "Return a safe proposal for opening Firefox.", format=STRUCTURED_SCHEMA)
    try:
        parsed = StructuredModelResponse.model_validate_json(result["response"])
        result["valid"] = True
        result["parsed"] = parsed.model_dump(mode="json")
    except Exception as error:
        result["valid"] = False
        result["parse_error"] = str(error)
    return result


def _tool_call_test(client: httpx.Client, base_url: str, model: str) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Propose a fake tool call to open Firefox. Do not perform it."}],
        "tools": FAKE_TOOLS,
        "stream": False,
        "options": {"temperature": 0, "num_predict": 128},
    }
    started = time.perf_counter()
    response = client.post(f"{base_url}/api/chat", json=payload)
    response.raise_for_status()
    message = response.json().get("message", {})
    return {"total_seconds": time.perf_counter() - started, "tool_calls": message.get("tool_calls", []), "content": message.get("content", "")}


def run_benchmark(model: str, base_url: str, output: Path, max_prompts: int) -> dict[str, Any]:
    config = BenchmarkConfig(max_prompts=max_prompts)
    started_at = datetime.now(timezone.utc)
    cpu_before = _cpu_times()
    with httpx.Client(timeout=httpx.Timeout(config.request_timeout_seconds, connect=5)) as client:
        validate_model_installed(model, _model_names(client, base_url))
        before = capture_snapshot()
        results = [_generate(client, base_url, model, prompt) for prompt in PROMPTS[:max_prompts]]
        structured = _structured_test(client, base_url, model)
        tool_calls = _tool_call_test(client, base_url, model)
        after = capture_snapshot()
    cpu_percent = _cpu_percent(cpu_before, _cpu_times())
    before.cpu_percent = cpu_percent
    after.cpu_percent = cpu_percent
    for result in results + [structured, tool_calls]:
        count = result.get("eval_count")
        duration_ns = result.get("eval_duration_ns")
        result["tokens_per_second"] = count / (duration_ns / 1_000_000_000) if count and duration_ns else None
    report = {
        "benchmark_started_at": started_at.isoformat(),
        "benchmark_finished_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "ollama_endpoint": base_url,
        "max_prompts": config.max_prompts,
        "prompts": list(PROMPTS[:max_prompts]),
        "resource_before": _snapshot_dict(before),
        "prompt_results": results,
        "structured_output": structured,
        "simulated_tool_call": tool_calls,
        "resource_after": _snapshot_dict(after),
        "thermal_telemetry": bool(before.temperatures_c or after.temperatures_c),
        "network_scope": "local Ollama endpoint only",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", help="Installed Ollama model tag")
    parser.add_argument("--ollama-host", default=OLLAMA_DEFAULT)
    parser.add_argument("--output", type=Path, default=Path("/tmp/jarvis-model-benchmark.json"))
    parser.add_argument("--max-prompts", type=int, default=len(PROMPTS))
    args = parser.parse_args()
    try:
        report = run_benchmark(args.model, args.ollama_host.rstrip("/"), args.output, args.max_prompts)
    except (httpx.HTTPError, ValueError, OSError, json.JSONDecodeError) as error:
        print(f"Benchmark failed safely: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"model": report["model"], "output": str(args.output), "prompts": report["max_prompts"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())