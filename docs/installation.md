# Installation

Phase 13 release: `0.13.0`.

The certified Phase 12 baseline is commit `4ab5c261131a6011ff1aba82d3024440fcd96d17`. The Phase 13 release records its own commit in Git history after validation. The supported interpreter is Python `3.14+`; the current validated interpreter is `3.14.7`.

## Fresh Kali installation

From a clone of this repository:

```bash
cd /path/to/JARVIS
PYTHON_BIN=python3.14 scripts/install.sh
```

The installer verifies Python, Git, and curl, creates `venv`, installs the declared base and development dependencies, creates `data/backups`, `data/run`, and `logs`, initializes the application database, checks the approved HUD asset, and probes the local Ollama endpoint. It does not install system packages or optional browser/audio/model packages.

Optional capabilities are installed only when needed:

```bash
venv/bin/python -m pip install -e '.[browser]'
venv/bin/python -m pip install -e '.[memory]'
venv/bin/python -m pip install -e '.[vision]'
venv/bin/python -m pip install -e '.[voice]'
```

The local model tag defaults to `llama3.2` and can be changed in the untracked `.env` file with `JARVIS_AGENT_MODEL`. Record the installed model digest with `ollama show "$JARVIS_AGENT_MODEL"` when certifying a machine. Cloud credentials are optional and belong only in `.env` or the environment.

## Release record

- Application version: `0.13.0`
- Configuration schema: `1`
- Python: `3.14+`
- Runtime dependencies: declared in `pyproject.toml`
- OS/kernel and model digest: machine-specific; capture with `scripts/diagnostics.sh`, `python --version`, `uname -sr`, and `ollama show <model>`
- HUD SHA-256: `10a788cef3a00614a37a7cf88d073fd6799635e0acae9f2fca1a2bfc48515a65`