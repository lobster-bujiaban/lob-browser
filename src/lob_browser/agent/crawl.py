"""Generic bounded crawler driven by a high-level crawl plan."""

from __future__ import annotations

from collections import deque
import re
from urllib.parse import urljoin, urlparse, urldefrag

from pydantic import BaseModel, Field

from lob_browser.actions import Action
from lob_browser.agent.models import CollectedItem, Decision, StepRecord
from lob_browser.observation import Observation


class CrawlPlan(BaseModel):
    start_url: str
    max_depth: int = Field(default=1, ge=0, le=3)
    max_pages: int = Field(default=20, ge=1, le=50)
    collect_external_only: bool = False
    follow_same_origin: bool = True
    fields: list[str] = Field(default_factory=lambda: ["url", "title", "content", "published_at", "author"])
    collect_url_pattern: str | None = None
    collect_article_details: bool = False


class GenericCrawler:
    continue_on_error_pages = True

    def __init__(self, plan: CrawlPlan) -> None:
        self.plan = plan
        self.root_host = urlparse(plan.start_url).hostname
        self.pending: deque[tuple[str, int]] = deque([(plan.start_url, 0)])
        self.depths: dict[str, int] = {_normalize(plan.start_url): 0}
        self.discovered_titles: dict[str, str] = {}
        self.visited: set[str] = set()
        self.collected: dict[str, CollectedItem] = {}

    async def __call__(self, task: str, observation: Observation, history: list[StepRecord]) -> Decision:
        current = _normalize(observation.url)
        if current == "about:blank":
            return Decision(thought="open crawl start URL", action=Action.navigate(self.plan.start_url))

        depth = self._current_depth(current)
        self.visited.add(current)
        self._extract(observation)
        self._discover(observation, depth)

        while self.pending and (self.pending[0][0] in self.visited or len(self.visited) >= self.plan.max_pages):
            self.pending.popleft()
        if self.pending and len(self.visited) < self.plan.max_pages:
            url, _ = self.pending.popleft()
            return Decision(thought=f"visit discovered page {len(self.visited) + 1}/{self.plan.max_pages}", action=Action.navigate(url))

        items = list(self.collected.values())
        if not items:
            return Decision(done=True, success=False, message="采集完成，但没有发现符合条件且 URL 非空的数据")
        message = f"采集完成，共获得 {len(items)} 条数据。"
        return Decision(done=True, success=True, message=message, collected_items=items)

    def _current_depth(self, current: str) -> int:
        if current == _normalize(self.plan.start_url):
            return 0
        return self.depths.get(current, 1)

    def _extract(self, observation: Observation) -> None:
        if self.plan.collect_article_details and _looks_like_article_url(observation.url):
            published = _extract_date(observation.text)
            content = observation.text.strip() or None
            self.collected[_normalize(observation.url)] = CollectedItem(
                url=_normalize(observation.url), title=self.discovered_titles.get(_normalize(observation.url)) or observation.title or None,
                content=content, published_at=published, author=_extract_author(observation.text),
            )
            return
        if self.plan.collect_article_details:
            return
        for element in observation.elements:
            if not element.href or element.href == "#":
                continue
            url = _normalize(urljoin(observation.url, element.href))
            host = urlparse(url).hostname
            if not host:
                continue
            if self.plan.collect_external_only and host == self.root_host:
                continue
            if self.plan.collect_url_pattern and self.plan.collect_url_pattern.lower() not in url.lower():
                continue
            self.collected.setdefault(url, CollectedItem(url=url, title=element.name or None))

    def _discover(self, observation: Observation, depth: int) -> None:
        if depth >= self.plan.max_depth:
            return
        known = self.visited | {url for url, _ in self.pending}
        for element in observation.elements:
            if not element.href or element.href == "#":
                continue
            url = _normalize(urljoin(observation.url, element.href))
            if url in known:
                continue
            host = urlparse(url).hostname
            if self.plan.follow_same_origin and host != self.root_host:
                continue
            if self.plan.collect_article_details:
                if depth != 0 or not _looks_like_article_url(url):
                    continue
                self.pending.append((url, depth + 1))
                self.depths[url] = depth + 1
                if element.name:
                    self.discovered_titles[url] = element.name
                known.add(url)
                continue
            if not _looks_like_navigation(element.class_name, element.name, url):
                continue
            self.pending.append((url, depth + 1))
            self.depths[url] = depth + 1
            known.add(url)


def _normalize(url: str) -> str:
    clean, _ = urldefrag(url)
    return clean.rstrip("/") or clean


def _looks_like_navigation(class_name: str | None, name: str, url: str) -> bool:
    marker = f"{class_name or ''} {name} {url}".lower()
    return any(term in marker for term in ("category", "column", "col_item", "栏目", "分类", "/list.", "/list/"))


def _looks_like_article_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return bool(re.search(r"/20\d{2}/\d{4}/c\d+a\d+", path) or re.search(r"/20\d{2}/\d{2}/\d{2}/", path))


def _extract_date(text: str) -> str | None:
    match = re.search(r"(?:20\d{2}|19\d{2})[-年/.](?:0?[1-9]|1[0-2])[-月/.](?:0?[1-9]|[12]\d|3[01])日?", text)
    return match.group(0) if match else None


def _extract_author(text: str) -> str | None:
    match = re.search(r"(?:作者|撰稿|来源)[:：]\s*([^\s|]{2,40})", text)
    return match.group(1) if match else None
