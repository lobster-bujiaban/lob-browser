"""OpenAI-compatible chat completions decider.

Uses the current observation summary as context. API key stays in the environment.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from pydantic import BaseModel

from lob_browser.actions import Action, ActionKind
from lob_browser.agent.models import Decision, StepRecord
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

    async def __call__(self, task: str, observation: Observation, history: list[StepRecord]) -> Decision:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        if observation.url == "about:blank":
            match = re.search(r"https?://[^\s，。；;]+", task)
            if match:
                return Decision(thought="open the target URL from the task", action=Action.navigate(match.group(0)))
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
