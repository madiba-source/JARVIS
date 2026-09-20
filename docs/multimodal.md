# Multimodal Intelligence

Current release version: `0.22.0`.

## Context

`app.multimodal` composes typed context items from user requests, voice transcripts, explicit screen observations, documents, memory, workflows, and tool state. Each item has a source, timestamp, bounded lifetime, sensitivity classification, and optional confidence. Context is ephemeral and is not automatically written to long-term memory.

## Screen and vision

Screen capture is explicit and on-demand. There is no always-on screenshot loop. Captures are bounded by the existing vision width, height, and byte limits and are rate-limited. Raw image bytes are not persisted. Local vision is used only when a configured provider is available; unavailable vision is a normal degraded state.

Actionable screen observations require a matching observation ID, fresh timestamp, valid dimensions, in-bounds coordinates, and confidence of at least `0.7`. A vision prediction is untrusted content and never authorizes a computer action. The existing computer-use controller and policy gateway remain authoritative.

`JarvisCore.disable()` cancels vision capture and disables multimodal context. Re-enable explicitly resets cancellation state; it does not start capture automatically.

## Voice

The existing push-to-talk audio runtime and local Whisper provider remain the voice path. Microphone capture is disabled by default, local model files are required, transcripts are bounded, and cancellation is supported. Voice text is input context only and cannot authorize privileged operations.

## Documents and OCR

`DocumentParser` supports bounded UTF-8 text, Markdown, source, JSON, TOML/YAML, CSV, optional PDF extraction through preinstalled `pypdf`, and injected OCR for common images. Parsing is local and explicit. Symlinks, unsupported formats, oversized files, malformed JSON, and unavailable OCR are rejected. OCR and document text are untrusted extracted content; they are never treated as policy or executable instructions.

Long-term memory ingestion remains separate and explicit through `KnowledgeIngestor`, which requires approval, uses the filesystem policy gateway, checks provenance and secrets, and supports existing memory deletion/correction flows. Raw screenshots and audio are not automatically stored.

## Routing and privacy

The Phase 16 context layer has no cloud client and defaults to local-only behavior. Existing model routing may use local-first policy with optional cloud fallback only where already configured and authorized. Screen/document/voice content is not sent to cloud providers by the new layer.

## Limitations

Active-window identity and OCR quality depend on the host capture/backend. PDF parsing requires `pypdf`; image OCR requires an explicitly supplied OCR provider. The phase does not add GUI widgets, continuous capture, browser prompt-injection trust, arbitrary tool calls, or new computer-control actions.
