"""Bounded discovery of installed Kali tools without executing them."""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass

from .models import ExecutionCode, ExecutionResult


@dataclass(frozen=True)
class KaliCapability:
    tool_id: str
    executable: str
    category: str
    aliases: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ("discover",)
    available: bool = True
    risk_level: int = 0
    requires_privileges: bool = False


# This is classification metadata only. A tool is reported only when its
# executable is present on PATH, and discovery never invokes it.
_CATEGORIES = {
    "aircrack-ng": "wireless",
    "airmon-ng": "wireless",
    "burpsuite": "web",
    "gobuster": "web",
    "hashcat": "password_security_auditing",
    "john": "password_security_auditing",
    "msfconsole": "exploitation",
    "ncat": "sniffing_spoofing",
    "nikto": "web",
    "nmap": "information_gathering",
    "radare2": "reverse_engineering",
    "rizin": "reverse_engineering",
    "sqlmap": "database",
    "tcpdump": "sniffing_spoofing",
    "tshark": "sniffing_spoofing",
    "volatility": "forensics",
    "wpscan": "web",
}


class KaliToolRegistry:
    def __init__(self, max_tools: int = 512, cache_ttl_seconds: float = 60.0) -> None:
        self.max_tools = max_tools
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cached: tuple[KaliCapability, ...] | None = None
        self._cached_at = 0.0

    def discover(self, refresh: bool = False) -> dict:
        tools = self._scan(refresh=refresh)
        return ExecutionResult(
            code=ExecutionCode.SUCCESS,
            message="Kali capabilities discovered",
            data={"capabilities": [tool.__dict__ for tool in tools], "count": len(tools), "refreshed": refresh},
        ).model_dump()

    def _scan(self, refresh: bool = False) -> tuple[KaliCapability, ...]:
        now = time.monotonic()
        if self._cached is not None and not refresh and now - self._cached_at < self.cache_ttl_seconds:
            return self._cached
        discovered: list[KaliCapability] = []
        for name, category in sorted(_CATEGORIES.items()):
            executable = shutil.which(name)
            if executable is None:
                continue
            discovered.append(KaliCapability(tool_id=name, executable=executable, category=category, aliases=(name,)))
            if len(discovered) >= self.max_tools:
                break
        self._cached = tuple(discovered)
        self._cached_at = now
        return self._cached