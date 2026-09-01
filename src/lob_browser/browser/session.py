"""Chromium session lifecycle: launch, CDP connect, isolated context, close.

Mapped from browser-use 0.13.7 (MIT):
- BrowserSession.start/connect/kill → this class
- LocalBrowserWatchdog subprocess + --remote-debugging-port → _launch_unlocked
- Playwright BrowserContext is the isolation boundary we keep explicit

Deliberate simplifications:
- no EventBus / Watchdogs / cdp-use
- one isolated context per session, not a shared default profile
- close() always disconnects; it only kills Chromium if this session launched it
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import socket
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Self
from uuid import uuid4

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from lob_browser.browser.errors import LastTabError, SessionError, SessionNotStartedError, TabNotFoundError
from lob_browser.browser.models import SessionConfig, SessionInfo, TabInfo

logger = logging.getLogger("lob_browser.browser")

_CHROMIUM_ARGS = (
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-sync",
    "--disable-default-apps",
    "--remote-allow-origins=*",
)


class BrowserSession:
    """Owns one isolated BrowserContext, optionally the Chromium process behind it."""

    def __init__(self, config: SessionConfig | None = None) -> None:
        self._config = config or SessionConfig()
        self._session_id = uuid4().hex[:12]
        self._start_lock = asyncio.Lock()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._pages: dict[str, Page] = {}
        self._current_tab_id: str | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._profile_dir: Path | None = None
        self._cdp_url: str | None = None
        self._owns_browser = False
        self._started = False

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def cdp_url(self) -> str | None:
        return self._cdp_url

    @property
    def started(self) -> bool:
        return self._started

    @property
    def owns_browser(self) -> bool:
        return self._owns_browser

    @property
    def config(self) -> SessionConfig:
        return self._config

    @property
    def current_tab_id(self) -> str | None:
        return self._current_tab_id

    @property
    def page(self) -> Page:
        if self._page is None:
            raise SessionNotStartedError("session is not started")
        return self._page

    @property
    def context(self) -> BrowserContext:
        if self._context is None:
            raise SessionNotStartedError("session is not started")
        return self._context

    async def __aenter__(self) -> Self:
        return await self.start()

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    async def start(self) -> Self:
        """Launch Chromium or attach via config.cdp_url. Idempotent while open."""
        async with self._start_lock:
            if self._started:
                return self
            try:
                if self._config.cdp_url:
                    await self._connect_unlocked(self._config.cdp_url, owns_browser=False)
                else:
                    await self._launch_unlocked()
            except BaseException:
                await self._cleanup_unlocked()
                raise
            return self

    async def connect(self, cdp_url: str) -> Self:
        """Attach to an already-running Chromium. Does not take ownership of the process."""
        async with self._start_lock:
            if self._started:
                if self._cdp_url == cdp_url:
                    return self
                raise SessionError("session already started; close() before connecting to another browser")
            try:
                await self._connect_unlocked(cdp_url, owns_browser=False)
            except BaseException:
                await self._cleanup_unlocked()
                raise
            return self

    async def close(self) -> None:
        """Close this context. Kill Chromium only if this session launched it."""
        async with self._start_lock:
            await self._cleanup_unlocked()

    def info(self) -> SessionInfo:
        tabs = [
            TabInfo(tab_id=tab_id, url=page.url, current=tab_id == self._current_tab_id)
            for tab_id, page in self._pages.items()
            if not page.is_closed()
        ]
        return SessionInfo(
            session_id=self._session_id,
            started=self._started,
            owns_browser=self._owns_browser,
            cdp_url=self._cdp_url,
            context_id=self._session_id if self._started else None,
            current_tab_id=self._current_tab_id,
            tabs=tabs,
        )

    async def list_tabs(self) -> list[TabInfo]:
        infos: list[TabInfo] = []
        for tab_id in list(self._pages):
            if self._pages[tab_id].is_closed():
                self._forget_page(tab_id)
                continue
            infos.append(await self._tab_info(tab_id))
        return infos

    async def new_tab(self, url: str | None = None, *, timeout_ms: float | None = None) -> TabInfo:
        if self._context is None:
            raise SessionNotStartedError("session is not started")
        page = await self._context.new_page()
        tab_id = self._register_page(page)
        self._focus(tab_id)
        await page.bring_to_front()
        if url:
            timeout = timeout_ms if timeout_ms is not None else self._config.timeout_ms
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        return await self._tab_info(tab_id)

    async def switch_tab(self, tab_id: str) -> TabInfo:
        page = self._require_tab(tab_id)
        self._focus(tab_id)
        await page.bring_to_front()
        return await self._tab_info(tab_id)

    async def close_tab(self, tab_id: str | None = None) -> str:
        target_id = tab_id or self._current_tab_id
        if not target_id:
            raise TabNotFoundError("")
        page = self._require_tab(target_id)
        open_tabs = [tid for tid, item in self._pages.items() if not item.is_closed()]
        if len(open_tabs) <= 1:
            raise LastTabError()
        await page.close()
        self._forget_page(target_id)
        if self._page is not None and not self._page.is_closed():
            await self._page.bring_to_front()
        return target_id

    def _on_new_page(self, page: Page) -> None:
        self._register_page(page)

    def _register_page(self, page: Page) -> str:
        for tab_id, existing in self._pages.items():
            if existing is page:
                return tab_id
        tab_id = uuid4().hex[:8]
        self._pages[tab_id] = page
        page.on("close", lambda _closed: self._forget_page(tab_id))
        return tab_id

    def _forget_page(self, tab_id: str) -> None:
        self._pages.pop(tab_id, None)
        if self._current_tab_id != tab_id:
            return
        remaining = next((tid for tid, item in self._pages.items() if not item.is_closed()), None)
        if remaining is None:
            self._current_tab_id = None
            self._page = None
            return
        self._focus(remaining)

    def _focus(self, tab_id: str) -> None:
        self._current_tab_id = tab_id
        self._page = self._pages[tab_id]

    def _require_tab(self, tab_id: str) -> Page:
        page = self._pages.get(tab_id)
        if page is None or page.is_closed():
            self._pages.pop(tab_id, None)
            raise TabNotFoundError(tab_id)
        return page

    async def _tab_info(self, tab_id: str) -> TabInfo:
        page = self._require_tab(tab_id)
        title = ""
        try:
            title = await page.title()
        except Exception:
            logger.debug("page.title() failed tab=%s", tab_id, exc_info=True)
        return TabInfo(tab_id=tab_id, url=page.url, title=title, current=tab_id == self._current_tab_id)

    async def _launch_unlocked(self) -> None:
        playwright = await async_playwright().start()
        self._playwright = playwright
        executable = playwright.chromium.executable_path
        if not Path(executable).exists():
            raise SessionError(
                "Chromium executable not found. Run: uv run playwright install chromium"
            )

        port = _free_tcp_port()
        profile_dir = Path(tempfile.mkdtemp(prefix=f"lob-browser-{self._session_id}-"))
        self._profile_dir = profile_dir
        cdp_url = f"http://127.0.0.1:{port}"

        args = [
            executable,
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={profile_dir}",
            *_CHROMIUM_ARGS,
        ]
        if self._config.headless:
            args.append("--headless=new")
        args.append("about:blank")

        logger.info("launching Chromium session=%s port=%s", self._session_id, port)
        self._process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._owns_browser = True
        await self._wait_cdp_ready(cdp_url)
        await self._connect_unlocked(cdp_url, owns_browser=True)

    async def _connect_unlocked(self, cdp_url: str, *, owns_browser: bool) -> None:
        if self._playwright is None:
            self._playwright = await async_playwright().start()

        timeout_ms = self._config.timeout_ms
        browser: Browser | None = None
        context: BrowserContext | None = None
        try:
            async with asyncio.timeout(timeout_ms / 1000):
                browser = await self._playwright.chromium.connect_over_cdp(cdp_url, timeout=timeout_ms)
            # New context, never the default one attached via CDP. That is the isolation boundary.
            context = await browser.new_context(
                viewport={
                    "width": self._config.viewport_width,
                    "height": self._config.viewport_height,
                },
            )
            context.set_default_timeout(timeout_ms)
            context.on("page", self._on_new_page)
            page = await context.new_page()
        except Exception:
            await _close_quietly(context)
            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    logger.debug("browser.close() failed during connect", exc_info=True)
            raise

        tab_id = self._register_page(page)
        self._browser = browser
        self._context = context
        self._focus(tab_id)
        self._cdp_url = cdp_url
        self._owns_browser = owns_browser
        self._started = True
        logger.info(
            "connected session=%s owns_browser=%s contexts=%s",
            self._session_id,
            owns_browser,
            len(browser.contexts),
        )

    async def _wait_cdp_ready(self, cdp_url: str) -> None:
        version_url = cdp_url.rstrip("/") + "/json/version"
        timeout_s = self._config.timeout_ms / 1000
        deadline = asyncio.get_running_loop().time() + timeout_s
        last_error: Exception | None = None

        while asyncio.get_running_loop().time() < deadline:
            if self._process is not None and self._process.returncode is not None:
                raise SessionError(f"Chromium exited before CDP became ready (code={self._process.returncode})")
            try:
                payload = await asyncio.to_thread(_read_json, version_url)
                if payload.get("webSocketDebuggerUrl"):
                    return
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                last_error = exc
            await asyncio.sleep(0.05)

        raise SessionError(f"timed out waiting for CDP at {version_url}: {last_error}")

    async def _cleanup_unlocked(self) -> None:
        self._started = False
        page, self._page = self._page, None
        self._pages.clear()
        self._current_tab_id = None
        context, self._context = self._context, None
        browser, self._browser = self._browser, None
        playwright, self._playwright = self._playwright, None
        process, self._process = self._process, None
        profile_dir, self._profile_dir = self._profile_dir, None
        owns_browser = self._owns_browser
        self._owns_browser = False
        self._cdp_url = None

        await _close_quietly(page)
        await _close_quietly(context)
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                logger.debug("browser.close() failed", exc_info=True)

        if playwright is not None:
            try:
                await playwright.stop()
            except Exception:
                logger.debug("playwright.stop() failed", exc_info=True)

        if owns_browser and process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                process.kill()
                await process.wait()

        if profile_dir is not None:
            shutil.rmtree(profile_dir, ignore_errors=True)

        self._cdp_url = None


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _read_json(url: str) -> dict[str, object]:
    with urllib.request.urlopen(url, timeout=0.5) as response:
        return json.loads(response.read().decode("utf-8"))


async def _close_quietly(closable: Page | BrowserContext | None) -> None:
    if closable is None:
        return
    try:
        await closable.close()
    except Exception:
        logger.debug("close() failed", exc_info=True)
