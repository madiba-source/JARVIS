# Configuration

Configuration is loaded from safe defaults, then untracked `.env` values with the `JARVIS_` prefix, then process environment variables. `.env.example` is a template and contains no credentials.

## Safe defaults

The default bind address is `127.0.0.1`, the Ollama endpoint is `http://127.0.0.1:11434`, the model tag is `llama3.2`, HUD and memory are enabled, vector memory is disabled, and application data is under `./data`.

## User and optional cloud configuration

Copy `.env.example` to `.env` and set only values needed on the local machine. Never commit `.env`. Cloud configuration is optional and must remain disabled unless its explicit privacy and policy settings are configured. Do not place API keys, tokens, passwords, private keys, or personal exports in tracked files.

## Hardware-specific configuration

Audio settings belong under `JARVIS_VOICE__...`; calendar settings under `JARVIS_CALENDAR__...`; memory settings under `JARVIS_MEMORY__...`. These are validated by Pydantic. Use `scripts/diagnostics.sh` to inspect available hardware without changing it.

## Development and tests

Tests should pass explicit `Settings(...)` values or isolated environment variables. Do not use a developer `.env` as a test fixture. The configuration schema version is `1`; a schema change requires a release note and migration plan.