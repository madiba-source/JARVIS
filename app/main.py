"""Minimal JARVIS boot validation entry point."""

import logging

import structlog

from .core import JarvisCore


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[structlog.processors.TimeStamper(fmt="iso"), structlog.processors.JSONRenderer()]
    )


def main() -> int:
    configure_logging()
    core = JarvisCore()
    core.start()
    core.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
