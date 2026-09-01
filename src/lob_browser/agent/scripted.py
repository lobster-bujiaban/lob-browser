"""Deterministic decider for the AHU smoke tasks. Not a model."""

from __future__ import annotations

from lob_browser.actions import Action
from lob_browser.agent.models import Decision, StepRecord
from lob_browser.observation import Observation

HOME = "https://www.ahu.edu.cn/"
OVERVIEW = "https://www.ahu.edu.cn/42/list.htm"
NOTICES = "https://www.ahu.edu.cn/tzgg/list.htm"


class ScriptedDecider:
    async def __call__(self, task: str, observation: Observation, history: list[StepRecord]) -> Decision:
        if "ahu.edu.cn" not in observation.url:
            return Decision(thought="open the campus site", action=Action.navigate(HOME))
        if "学校概况" in task or "学校简介" in task:
            return self._overview(observation)
        if "页码" in task:
            return self._page_number(observation)
        if "通知公告" in task:
            return self._notices(observation)
        return Decision(done=True, success=False, message="unknown task", thought="cannot handle task")

    def _overview(self, observation: Observation) -> Decision:
        if "学校简介" in observation.title or "/42/list.htm" in observation.url:
            return Decision(done=True, success=True, message="on overview", thought="already there")
        target = observation.find_name("学校概况")
        if target is None:
            return Decision(thought="overview link missing, navigate", action=Action.navigate(OVERVIEW))
        return Decision(
            thought=f"click 学校概况 [{target.index}]",
            action=Action.click(index=target.index, observation_id=observation.observation_id),
        )

    def _notices(self, observation: Observation) -> Decision:
        if "通知公告" in observation.title or "/tzgg/" in observation.url:
            return Decision(done=True, success=True, message="on notices", thought="already there")
        target = _href_contains(observation, "tzgg") or observation.find_name("通知公告")
        if target is None:
            return Decision(thought="notices link missing, navigate", action=Action.navigate(NOTICES))
        return Decision(
            thought=f"click notices [{target.index}]",
            action=Action.click(index=target.index, observation_id=observation.observation_id),
        )

    def _page_number(self, observation: Observation) -> Decision:
        if "/tzgg/" not in observation.url:
            return Decision(thought="need notices page first", action=Action.navigate(NOTICES))
        field = next((item for item in observation.elements if item.class_name == "pageNum"), None)
        if field is None:
            return Decision(done=True, success=False, message="pageNum missing", thought="no page input")
        if field.value == "2":
            return Decision(done=True, success=True, message="page number is 2", thought="goal met")
        return Decision(
            thought=f"type 2 into pageNum [{field.index}]",
            action=Action.type_text(index=field.index, text="2", observation_id=observation.observation_id),
        )


def _href_contains(observation: Observation, fragment: str):
    for item in observation.elements:
        if item.href and fragment in item.href:
            return item
    return None
