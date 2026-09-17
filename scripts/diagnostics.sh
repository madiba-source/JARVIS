#!/usr/bin/env bash
set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="$PROJECT_ROOT/venv/bin/python"

section() { printf '\n-- %s --\n' "$1"; }
command_result() {
	local label="$1" command_name="$2"
	if command -v "$command_name" >/dev/null 2>&1; then
		printf '%s: PASS (%s)\n' "$label" "$(command -v "$command_name")"
	else
		printf '%s: OPTIONAL/MISSING\n' "$label"
	fi
}

printf '%s\n' '--------------------------------------------------' 'JARVIS HOST DIAGNOSTICS' '--------------------------------------------------'
section 'Operating system'
if [[ -r /etc/os-release ]]; then . /etc/os-release; printf 'Operating System: %s\n' "${PRETTY_NAME:-unknown}"; else printf 'Operating System: WARNING unavailable\n'; fi
printf 'Kernel: %s\nArchitecture: %s\nUser: %s\n' "$(uname -sr)" "$(uname -m)" "$(id -un)"

section 'Hardware'
if command -v lscpu >/dev/null 2>&1; then
	printf 'CPU: %s\n' "$(lscpu | awk -F: '/Model name/ {gsub(/^ +/, "", $2); print $2; exit}')"
	printf 'CPU cores/threads: %s\n' "$(lscpu | awk -F: '/^CPU\(s\)/ {gsub(/^ +/, "", $2); print $2; exit}')"
else printf 'CPU: OPTIONAL/MISSING lscpu\n'; fi
if command -v free >/dev/null 2>&1; then printf 'RAM: %s\n' "$(free -h | awk '/^Mem:/ {print $2}')"; else printf 'RAM: WARNING unavailable\n'; fi
printf 'Disk: %s\n' "$(df -h "$PROJECT_ROOT" | awk 'NR==2 {print $4 " available of " $2}')"
if command -v lspci >/dev/null 2>&1; then lspci | grep -Ei 'vga|3d|display' || printf 'GPU: none reported\n'; else printf 'GPU: OPTIONAL/MISSING lspci\n'; fi
if command -v glxinfo >/dev/null 2>&1; then glxinfo -B 2>/dev/null | grep -E 'OpenGL renderer|direct rendering' || true; else printf 'Graphics acceleration: OPTIONAL/MISSING glxinfo\n'; fi

section 'Required developer tooling'
command_result 'Git' git
command_result 'VS Code' code
if [[ -x "$VENV_PYTHON" ]]; then printf 'Virtual environment: PASS (%s)\n' "$VENV_PYTHON"; else printf 'Virtual environment: BLOCKER/MISSING (%s)\n' "$VENV_PYTHON"; fi
if [[ -x "$VENV_PYTHON" ]]; then printf 'Python: %s\nPython executable: %s\n' "$($VENV_PYTHON --version 2>&1)" "$($VENV_PYTHON -c 'import sys; print(sys.executable)')"; fi

section 'Ollama'
command_result 'Ollama CLI' ollama
if command -v systemctl >/dev/null 2>&1; then printf 'Ollama service: enabled=%s active=%s\n' "$(systemctl is-enabled ollama 2>/dev/null || printf unknown)" "$(systemctl is-active ollama 2>/dev/null || printf unknown)"; fi
if command -v curl >/dev/null 2>&1; then
	if curl -fsS --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null; then printf 'Ollama local endpoint: PASS (127.0.0.1:11434)\n'; else printf 'Ollama local endpoint: WARNING unreachable\n'; fi
fi
if command -v ollama >/dev/null 2>&1; then printf 'Installed models:\n'; ollama list 2>/dev/null || printf 'WARNING unable to list models\n'; fi

section 'Audio and media'
command_result 'FFmpeg' ffmpeg
if command -v pactl >/dev/null 2>&1; then
	printf 'Audio server: PASS\n'; printf 'Audio outputs:\n'; pactl list short sinks 2>/dev/null || true; printf 'Audio inputs:\n'; pactl list short sources 2>/dev/null || true
else printf 'Audio server: OPTIONAL/MISSING pactl (no installation attempted)\n'; fi
if [[ -x "$VENV_PYTHON" ]]; then "$VENV_PYTHON" -c 'import pygame; print("pygame-ce: PASS")' 2>/dev/null || printf 'pygame-ce: BLOCKER import failed\n'; fi

section 'Optional tooling'
for tool in firefox chromium chromium-browser google-chrome docker; do command_result "$tool" "$tool"; done

section 'Important Python packages'
if [[ -x "$VENV_PYTHON" ]]; then
	"$VENV_PYTHON" - <<'PY'
import importlib
packages = {"pydantic": "pydantic", "pydantic-settings": "pydantic_settings", "sqlalchemy": "sqlalchemy", "alembic": "alembic", "fastapi": "fastapi", "uvicorn": "uvicorn", "httpx": "httpx", "structlog": "structlog", "pytest": "pytest", "pytest-asyncio": "pytest_asyncio", "PySide6": "PySide6", "pygame-ce": "pygame", "ollama": "ollama"}
for label, module in packages.items():
	try:
		loaded = importlib.import_module(module)
		print(f"{label}: PASS ({getattr(loaded, '__version__', 'imported')})")
	except Exception as error:
		print(f"{label}: BLOCKER {error}")
PY
fi

printf '\n%s\n' 'Diagnostics complete (read-only).'
