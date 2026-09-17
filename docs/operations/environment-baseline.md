# JARVIS Environment Baseline

Baseline date: 2026-09-17

This report records the Phase 01 validation performed on the local host. It contains no credentials.

## Host

- OS: Kali GNU/Linux Rolling 2026.3
- Kernel: Linux 7.1.5+kali-amd64 x86_64
- Architecture: x86_64
- User: `master` (normal user; no root execution used)
- CPU: Intel Core i5-8350U @ 1.70 GHz, 4 cores / 8 threads
- RAM: 15 GiB RAM, 12 GiB swap
- Disk: 198 GiB available on the project filesystem at baseline
- GPU: Intel UHD Graphics 620 (Kaby Lake-R GT2)
- Graphics acceleration: `glxinfo` is not installed, so acceleration was not independently reported

## Python

- Version: Python 3.14.7
- Virtual environment: `/home/master/JARVIS/venv`
- Executable: `/home/master/JARVIS/venv/bin/python3`
- Package installer: pip 26.2.1

Validated imports include Pydantic, pydantic-settings, SQLAlchemy, Alembic, FastAPI, Uvicorn, HTTPX, structlog, pytest, pytest-asyncio, PySide6, pygame-ce, and ollama.

## Ollama

- CLI: 0.34.1
- Service: enabled and active
- Local endpoint: `http://127.0.0.1:11434` responded to `/api/tags`
- Models: none installed; no model was downloaded during Phase 01

## Audio and GUI

- FFmpeg: installed at `/usr/bin/ffmpeg`
- ALSA audio hardware: Intel Sunrise Point-LP HD Audio was reported by `lspci`
- PulseAudio/PipeWire query tool: `pactl` is missing, so output/input device enumeration remains a warning
- pygame-ce import: validated by the test suite and diagnostics
- PySide6 import and headless `QApplication` initialization: validated by the test suite

## Developer tooling

- Git: installed
- VS Code CLI: installed
- Browser: Firefox is installed at `/usr/bin/firefox`; no Chromium executable was found
- Docker: no executable was found during discovery

## Known limitations and remediation

- Install the distribution package providing `pactl` only when audio device enumeration is needed; no system package installation was performed by Phase 01.
- Install `glxinfo` only when direct graphics acceleration reporting is needed.
- Select and benchmark a suitably small local Ollama model in a later phase; this host has integrated graphics and limited RAM.

## Security baseline

- Services default to loopback binding.
- Cloud credentials are not required for boot or tests.
- `.env` files, virtual environments, databases, logs, screenshots, audio, and model files are excluded from Git.
- The Phase 01 code performs no shell execution, automation, privileged operations, or destructive host changes.
