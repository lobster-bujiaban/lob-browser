"""Deterministic check: launch, isolate two contexts, connect over CDP, close."""

from __future__ import annotations

import asyncio
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from lob_browser.browser import BrowserSession, SessionConfig, SessionNotStartedError

PAGE_HTML = b"<html><body><h1>lob-browser session</h1></body></html>"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(PAGE_HTML)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def _start_server() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}/"


async def _cookie_names(session: BrowserSession, url: str) -> set[str]:
    cookies = await session.context.cookies(url)
    return {cookie["name"] for cookie in cookies}


async def main() -> None:
    server, url = _start_server()
    owner = BrowserSession(SessionConfig(headless=True))
    peer = BrowserSession(SessionConfig(headless=True))
    try:
        await owner.start()
        assert owner.started
        assert owner.owns_browser
        assert owner.cdp_url
        await owner.start()  # idempotent
        await owner.page.goto(url)
        print(json.dumps({"launch": owner.info().model_dump()}, ensure_ascii=False))

        await peer.connect(owner.cdp_url)
        assert peer.started
        assert not peer.owns_browser
        await peer.page.goto(url)

        await owner.context.add_cookies(
            [{"name": "lob_owner", "value": "1", "url": url}],
        )
        await owner.page.evaluate("localStorage.setItem('from', 'owner')")

        peer_cookies = await _cookie_names(peer, url)
        peer_storage = await peer.page.evaluate("localStorage.getItem('from')")
        if "lob_owner" in peer_cookies or peer_storage is not None:
            raise SystemExit(
                f"context isolation failed: cookies={sorted(peer_cookies)} storage={peer_storage!r}"
            )

        await peer.close()
        try:
            _ = peer.page
            raise SystemExit("closed session still exposed page")
        except SessionNotStartedError:
            pass

        await owner.close()
        try:
            _ = owner.page
            raise SystemExit("closed owner still exposed page")
        except SessionNotStartedError:
            pass

        print("session lifecycle ok")
    finally:
        await peer.close()
        await owner.close()
        server.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
