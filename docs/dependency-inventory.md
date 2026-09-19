# Dependency and Model Inventory

This inventory records installed versions observed during the final integration
run. `UNVERIFIED` means installed metadata did not declare a license.

| Package | Version | Purpose | License metadata | Core/optional |
| --- | --- | --- | --- | --- |
| alembic | 1.20.0 | database migrations | UNVERIFIED | core |
| fastapi | 0.141.1 | API surface | UNVERIFIED | core metadata |
| httpx | 0.28.1 | bounded HTTP transports | BSD-3-Clause | core |
| numpy | 2.5.3 | audio/vision processing | UNVERIFIED | core |
| ollama | 0.6.2 | local model transport | UNVERIFIED | core |
| pydantic | 2.13.5 | typed validation | UNVERIFIED | core |
| pydantic-settings | 2.15.0 | configuration | UNVERIFIED | core |
| PySide6 | 6.11.2 | GUI capability | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | optional |
| pygame-ce | 2.5.8 | audio output | LGPL v2.1 | optional |
| sqlalchemy | 2.0.54 | database support | MIT | core |
| structlog | 26.1.0 | structured logging | UNVERIFIED | core |
| uvicorn | 0.53.0 | ASGI serving | UNVERIFIED | optional |
| pytest | 9.1.1 | test runner | UNVERIFIED | development |

No paid service is mandatory. Cloud inference is optional and disabled by
default. No model binaries are stored in Git and no model is downloaded
automatically. The configured local model default is `llama3.2`; its installed
version, quantization, and license are not discoverable from this repository.

License values marked `UNVERIFIED` require source or distribution verification
before a legal production certification claim.