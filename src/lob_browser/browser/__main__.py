"""Deterministic check: launch, isolate two contexts, connect over CDP, close."""

from __future__ import annotations

import asyncio
import json

from lob_browser.browser import BrowserSession, SessionConfig, SessionNotStartedError

HOME = "https://www.ahu.edu.cn/"


async def _cookie_names(session: BrowserSession, url: str) -> set[str]:
    cookies = await session.context.cookies(url)
    return {cookie["name"] for cookie in cookies}


async def main() -> None:
    owner = BrowserSession(SessionConfig(headless=True))
    peer = BrowserSession(SessionConfig(headless=True))
    try:
        await owner.start()
        assert owner.started
        assert owner.owns_browser
        assert owner.cdp_url
        await owner.start()  # idempotent
        await owner.page.goto(HOME, wait_until="domcontentloaded")
        print(json.dumps({"launch": owner.info().model_dump()}, ensure_ascii=False))

        await peer.connect(owner.cdp_url)
        assert peer.started
        assert not peer.owns_browser
        await peer.page.goto(HOME, wait_until="domcontentloaded")

        await owner.context.add_cookies(
            [{"name": "lob_owner", "value": "1", "url": HOME}],
        )
        await owner.page.evaluate("localStorage.setItem('from', 'owner')")

        peer_cookies = await _cookie_names(peer, HOME)
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


if __name__ == "__main__":
    asyncio.run(main())
