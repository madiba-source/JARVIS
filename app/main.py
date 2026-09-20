"""JARVIS foreground process and boot validation entry point."""

import argparse
import logging
import signal
from threading import Event

import structlog

from .core import JarvisCore
from .version import __version__


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[structlog.processors.TimeStamper(fmt="iso"), structlog.processors.JSONRenderer()]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run JARVIS locally.")
    parser.add_argument("--foreground", action="store_true", help="keep managed services running")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    configure_logging()
    core = JarvisCore()
    if not args.foreground:
        core.start()
        core.shutdown()
        return 0

    stopped = Event()

    def request_shutdown(signum: int, _frame: object) -> None:
        logging.getLogger("jarvis.core").info("JARVIS shutdown requested", extra={"signal": signum})
        stopped.set()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    core.start()
    try:
        stopped.wait()
    finally:
        core.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
