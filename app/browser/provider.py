"""Optional Playwright browser provider with no model-facing Playwright objects."""

from __future__ import annotations

import threading
from typing import Any

from .config import BrowserConfig
from .models import BrowserElement, BrowserObservation, BrowserState, LocatorStrategy
from .url import validate_url


class BrowserUnavailable(RuntimeError):
    pass


class BrowserProvider:
    """Small typed provider boundary; implementation details stay private."""

    def __init__(self, config: BrowserConfig | None = None) -> None:
        self.config = config or BrowserConfig()
        self._lock = threading.RLock()
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._state = BrowserState.CLOSED
        self._actions = 0
        self._cancelled = False

    @property
    def state(self) -> BrowserState:
        with self._lock:
            return self._state

    def ensure_started(self) -> None:
        if self.state is BrowserState.CLOSED:
            self.launch()

    def launch(self) -> None:
        with self._lock:
            if not self.config.enabled:
                self._state = BrowserState.DISABLED
                raise BrowserUnavailable("browser disabled")
            if self._state is BrowserState.READY:
                return
            self._state = BrowserState.STARTING
        try:
            from playwright.sync_api import sync_playwright
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.firefox.launch(headless=not self.config.headed)
            self._context = self._browser.new_context()
            self._page = self._context.new_page()
            self._page.set_default_timeout(self.config.action_timeout_ms)
            with self._lock:
                self._state = BrowserState.READY
                self._actions = 0
                self._cancelled = False
        except Exception as error:
            self.close()
            with self._lock:
                self._state = BrowserState.FAILED
            raise BrowserUnavailable(type(error).__name__) from None

    def close(self) -> None:
        with self._lock:
            self._state = BrowserState.SHUTTING_DOWN
            browser, playwright = self._browser, self._playwright
            self._browser = self._context = self._page = self._playwright = None
        for resource, method in ((browser, "close"), (playwright, "stop")):
            try:
                if resource is not None:
                    getattr(resource, method)()
            except Exception:
                pass
        with self._lock:
            self._state = BrowserState.CLOSED

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            if self._state not in {BrowserState.CLOSED, BrowserState.DISABLED}:
                self._state = BrowserState.CANCELLED

    def _page_or_raise(self) -> Any:
        with self._lock:
            if self._cancelled:
                raise BrowserUnavailable("browser operation cancelled")
            page = self._page
        if page is None:
            raise BrowserUnavailable("browser session unavailable")
        return page

    def _count_action(self) -> None:
        with self._lock:
            self._actions += 1
            if self._actions > self.config.max_actions:
                raise BrowserUnavailable("browser action limit reached")

    def navigate(self, url: str, timeout_ms: int | None = None) -> BrowserObservation:
        self._count_action()
        page = self._page_or_raise()
        target = validate_url(url)
        with self._lock:
            self._state = BrowserState.NAVIGATING
        try:
            page.goto(target, timeout=timeout_ms or self.config.navigation_timeout_ms,
                      wait_until="domcontentloaded")
            result = self.inspect()
            return result
        finally:
            with self._lock:
                if self._state is BrowserState.NAVIGATING:
                    self._state = BrowserState.READY

    def inspect(self) -> BrowserObservation:
        page = self._page_or_raise()
        with self._lock:
            self._state = BrowserState.OBSERVING
        try:
            url = str(page.url)[:4096]
            title = str(page.title())[:512]
            text = str(page.locator("body").inner_text(timeout=self.config.action_timeout_ms))
            text = text[:self.config.max_extracted_chars]
            truncated = len(text) >= self.config.max_extracted_chars
            elements: list[BrowserElement] = []
            for locator in ("button", "a", "input", "select", "textarea"):
                count = min(page.locator(locator).count(), self.config.max_elements - len(elements))
                for index in range(max(0, count)):
                    item = page.locator(locator).nth(index)
                    elements.append(BrowserElement(role=locator, name=(item.get_attribute("aria-label") or "")[:256], locator=f"{locator}:nth={index}"))
            observation = BrowserObservation().refreshed(url=url, title=title,
                                                          visible_text=text,
                                                          elements=tuple(elements))
            return observation.model_copy(update={"truncated": truncated})
        finally:
            with self._lock:
                if self._state is BrowserState.OBSERVING:
                    self._state = BrowserState.READY

    def _locator(self, strategy: LocatorStrategy, target: str) -> Any:
        page = self._page_or_raise()
        if strategy is LocatorStrategy.ROLE:
            return page.get_by_role(target)
        if strategy is LocatorStrategy.LABEL:
            return page.get_by_label(target)
        if strategy is LocatorStrategy.TEXT:
            return page.get_by_text(target)
        if strategy is LocatorStrategy.CSS and target.startswith(("#", ".", "[")):
            return page.locator(target)
        raise BrowserUnavailable("unsupported locator")

    def click(self, strategy: LocatorStrategy, target: str, timeout_ms: int | None = None) -> BrowserObservation:
        self._count_action()
        with self._lock:
            self._state = BrowserState.ACTING
        try:
            self._locator(strategy, target).click(timeout=timeout_ms or self.config.action_timeout_ms)
            return self.inspect()
        finally:
            with self._lock:
                if self._state is BrowserState.ACTING:
                    self._state = BrowserState.READY

    def type_text(self, strategy: LocatorStrategy, target: str, text: str,
                  timeout_ms: int | None = None) -> BrowserObservation:
        self._count_action()
        with self._lock:
            self._state = BrowserState.ACTING
        try:
            self._locator(strategy, target).fill(text[:4096], timeout=timeout_ms or self.config.action_timeout_ms)
            return self.inspect()
        finally:
            with self._lock:
                if self._state is BrowserState.ACTING:
                    self._state = BrowserState.READY

    def health(self) -> dict[str, Any]:
        return {"state": self.state.value, "available": self.state is BrowserState.READY,
                "playwright": self._playwright is not None}