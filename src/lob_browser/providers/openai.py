"""OpenAI-compatible chat completions decider.

Uses the current observation summary as context. API key stays in the environment.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from pydantic import BaseModel

from lob_browser.actions import Action, ActionKind
from lob_browser.agent.models import Decision, StepRecord
from lob_browser.observation import Observation

_SYSTEM = """You are a browser agent. Pick one structured action per turn from the observation.
Use element indexes from the current observation only. Set done=true when the task is complete.
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
        if parsed.done:
            return Decision(thought=parsed.thought, done=True, success=parsed.success, message=parsed.message)
        if parsed.kind is None:
            return Decision(thought=parsed.thought, done=True, success=False, message="model returned no action")
        action = Action(
            kind=parsed.kind,
            url=parsed.url,
            index=parsed.index,
            selector=parsed.selector,
            text=parsed.text,
            value=parsed.value,
            tab_id=parsed.tab_id,
            amount=parsed.amount,
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
