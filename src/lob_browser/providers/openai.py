"""OpenAI-compatible chat completions decider.

Uses the current observation summary as context. API key stays in the environment.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlparse

from pydantic import BaseModel

from lob_browser.actions import Action, ActionKind
from lob_browser.agent.models import CollectedItem, Decision, StepRecord
from lob_browser.agent.crawl import CrawlPlan
from lob_browser.observation import Observation

_SYSTEM = """You are a browser agent. Return exactly one JSON object per turn.
For an action use: {"thought":"...","done":false,"success":false,"kind":"navigate|click|type|select|scroll|wait|back|reload|new_tab|switch_tab|close_tab|dialog|upload","url":null,"index":null,"text":null,"value":null}.
For completion use: {"thought":"...","done":true,"success":true,"message":"result"}.
Use element indexes from the current observation only. Never omit kind when done=false.
Never include passwords or other secret field values in thought or message."""


class ModelAction(BaseModel):
    thought: str = ""
    done: bool = False
    success: bool = False
    message: str = ""
    kind: ActionKind | None = None
    url: str | None = None
    index: int | None = None
    selector: str | None = None
    text: str | None = None
    value: str | None = None
    tab_id: str | None = None
    direction: str | None = None
    amount: int | None = None
    action: "ModelAction | None" = None


class OpenAICompatibleDecider:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self._collected_links: dict[str, CollectedItem] = {}
        self._pending_sections: list[str] | None = None
        self._pending_category_urls: list[str] | None = None

    async def __call__(self, task: str, observation: Observation, history: list[StepRecord]) -> Decision:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        if observation.url == "about:blank":
            match = re.search(r"https?://[^\s，。；;]+", task)
            if match:
                return Decision(thought="open the target URL from the task", action=Action.navigate(match.group(0)))
        extracted = _deterministic_extraction(self, task, observation)
        if extracted is not None:
            return extracted
        hierarchical = _hierarchical_site_extraction(self, task, observation)
        if hierarchical is not None:
            return hierarchical
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": _user_prompt(task, observation, history)},
            ],
        }
        data = await _post_json(f"{self.base_url}/chat/completions", payload, self.api_key)
        content = data["choices"][0]["message"]["content"]
        parsed = ModelAction.model_validate(json.loads(content))
        action_data = parsed.action or parsed
        if parsed.done:
            return Decision(thought=parsed.thought, done=True, success=parsed.success, message=parsed.message)
        if action_data.kind is None:
            compact = content.replace("\n", " ")[:300]
            return Decision(thought=parsed.thought, done=True, success=False, message=f"model returned no action: {compact}")
        if action_data.kind is ActionKind.CLICK and action_data.index is not None:
            target = observation.element(action_data.index)
            if target and target.tag == "a" and target.href and target.href != "#":
                return Decision(thought=f"use stable link navigation instead of clicking stale index {action_data.index}", action=Action.navigate(urljoin(observation.url, target.href)))
        action = Action(
            kind=action_data.kind,
            url=action_data.url,
            index=action_data.index,
            selector=action_data.selector,
            text=action_data.text,
            value=action_data.value,
            tab_id=action_data.tab_id,
            amount=action_data.amount,
            observation_id=observation.observation_id,
        )
        return Decision(thought=parsed.thought, action=action)


def _user_prompt(task: str, observation: Observation, history: list[StepRecord]) -> str:
    recent = history[-4:]
    errors = [item.error for item in recent if item.error]
    return (
        f"Task: {task}\n"
        f"Recent errors: {errors or 'none'}\n"
        f"Observation:\n{observation.summary(max_elements=60)}"
    )


def _deterministic_extraction(decider: OpenAICompatibleDecider, task: str, observation: Observation) -> Decision | None:
    intent = task.lower()
    if not any(term in intent for term in ("所有网址", "所有链接", "全部网址", "全部链接", "all urls", "all links")):
        return None
    elements = []
    seen = set()
    for item in observation.elements:
        if item.href and item.href not in seen:
            seen.add(item.href)
            elements.append(item)
    if not elements:
        return None
    for item in elements:
        decider._collected_links.setdefault(item.href, CollectedItem(url=item.href, title=item.name or None))

    normalized = intent.replace(" ", "")
    wants_multiple_sections = sum(term in normalized for term in ("工作台", "ai工具", "创作")) >= 2
    if wants_multiple_sections:
        if decider._pending_sections is None:
            decider._pending_sections = [name for name in ("AI 工具", "创作") if name.replace(" ", "").lower() in normalized]
        while decider._pending_sections:
            section = decider._pending_sections.pop(0)
            target = next((item for item in observation.elements if item.name.replace(" ", "").lower() == section.replace(" ", "").lower()), None)
            if target is not None:
                return Decision(thought=f"collect the next requested section: {section}", action=Action.click(index=target.index, observation_id=observation.observation_id))

    collected = list(decider._collected_links.values())
    message = f"共采集到 {len(collected)} 个网址：\n" + "\n".join(f"{index}. {item.url}" for index, item in enumerate(collected, 1))
    return Decision(thought="all requested links are available in the current observation", done=True, success=True, message=message, collected_items=collected)


def _hierarchical_site_extraction(decider: OpenAICompatibleDecider, task: str, observation: Observation) -> Decision | None:
    normalized = task.replace(" ", "").lower()
    if not any(term in normalized for term in ("所有二级独立站点", "全部二级独立站点", "所有独立站点")):
        return None
    page_host = urlparse(observation.url).hostname
    for item in observation.elements:
        if not item.href or item.href == "#":
            continue
        absolute = urljoin(observation.url, item.href)
        target_host = urlparse(absolute).hostname
        if target_host and target_host != page_host and item.bbox and item.bbox.y > 280:
            decider._collected_links.setdefault(absolute, CollectedItem(url=absolute, title=item.name or None))

    if decider._pending_category_urls is None:
        category_urls = []
        for item in observation.elements:
            if item.class_name == "col_item_link" and item.href:
                absolute = urljoin(observation.url, item.href)
                if absolute not in category_urls:
                    category_urls.append(absolute)
        decider._pending_category_urls = category_urls

    while decider._pending_category_urls:
        target = decider._pending_category_urls.pop(0)
        if target.rstrip("/") != observation.url.rstrip("/"):
            return Decision(thought=f"visit the next category page: {target}", action=Action.navigate(target))

    collected = list(decider._collected_links.values())
    if not collected:
        return Decision(done=True, success=False, message="未在分类正文区域发现二级独立站点")
    message = f"共采集到 {len(collected)} 个二级独立站点：\n" + "\n".join(f"{index}. {item.title or '未命名'} — {item.url}" for index, item in enumerate(collected, 1))
    return Decision(thought="all category pages have been visited", done=True, success=True, message=message, collected_items=collected)


async def _post_json(url: str, payload: dict, api_key: str) -> dict:
    import asyncio

    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    def _send() -> dict:
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"model HTTP {exc.code}: {detail[:300]}") from exc

    return await asyncio.to_thread(_send)


async def plan_crawl(task: str) -> CrawlPlan | None:
    normalized = task.lower()
    if not any(term in normalized for term in ("采集", "抓取", "爬取", "遍历", "所有网址", "所有链接", "crawl", "scrape")):
        return None
    match = re.search(r"https?://[^\s，。；;]+", task)
    if not match:
        return None
    api_key = os.environ.get("OPENAI_API_KEY", "")
    fallback = CrawlPlan(
        start_url=match.group(0),
        max_depth=1 if any(term in normalized for term in ("二级", "分类", "栏目", "所有")) else 0,
        max_pages=20,
        collect_external_only=any(term in normalized for term in ("独立站点", "外部站点", "外链")),
        collect_url_pattern="list." if any(term in normalized for term in ("所有列表页", "全部列表页", "列表页面")) else None,
    )
    if not api_key:
        return fallback
    payload = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "Convert web collection requests into a bounded crawl plan JSON with keys: start_url, max_depth (0-3), max_pages (1-50), collect_external_only, follow_same_origin, fields, collect_url_pattern (optional substring such as list.). Return {\"crawl\":false} when the request is an interactive browser task rather than collection."},
            {"role": "user", "content": task},
        ],
    }
    try:
        data = await _post_json(f"{os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1').rstrip('/')}/chat/completions", payload, api_key)
        parsed = json.loads(data["choices"][0]["message"]["content"])
        if parsed.get("crawl") is False:
            return None
        if fallback.collect_url_pattern and not parsed.get("collect_url_pattern"):
            parsed["collect_url_pattern"] = fallback.collect_url_pattern
        return CrawlPlan.model_validate({**fallback.model_dump(), **parsed})
    except Exception:
        return fallback
