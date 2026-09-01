"""Deterministic decider for stable local acceptance tasks."""

from __future__ import annotations

from pathlib import Path

from lob_browser.actions import Action
from lob_browser.agent.models import Decision, StepRecord
from lob_browser.observation import Observation


class LocalScriptedDecider:
    def __init__(self, fixtures_dir: str | Path) -> None:
        root = Path(fixtures_dir).resolve()
        self.home = (root / "index.html").as_uri()
        self.detail = (root / "detail.html").as_uri()

    async def __call__(self, task: str, observation: Observation, history: list[StepRecord]) -> Decision:
        if "表单" in task:
            return self._form(observation)
        if "动态列表" in task:
            return self._dynamic(observation)
        if "多标签" in task:
            return self._tabs(observation)
        return Decision(done=True, success=False, message="unknown local task")

    def _form(self, observation: Observation) -> Decision:
        if "提交成功" in observation.text:
            return Decision(done=True, success=True, message="form submitted")
        if observation.title != "表单任务":
            return self._click_or_home(observation, "表单任务")
        name = observation.find_name("姓名")
        if name and name.value != "小龙":
            return self._type(name.index, observation, "小龙")
        track = observation.find_name("方向")
        if track and track.value != "browser":
            return Decision(action=Action.select(index=track.index, value="browser", observation_id=observation.observation_id))
        return self._click(observation, "提交")

    def _dynamic(self, observation: Observation) -> Decision:
        if observation.title == "项目详情" and "LOB-001" in observation.text:
            return Decision(done=True, success=True, message="dynamic result opened")
        if observation.title != "动态列表":
            return self._click_or_home(observation, "动态列表")
        result = observation.find_name("LOB Browser")
        if result:
            return self._click(observation, "LOB Browser")
        query = observation.find_name("搜索词")
        if query and query.value != "LOB":
            return self._type(query.index, observation, "LOB")
        if "加载中" in observation.text:
            return Decision(action=Action.wait(250), thought="wait for async results")
        return self._click(observation, "搜索")

    def _tabs(self, observation: Observation) -> Decision:
        if observation.title == "项目详情" and "LOB-001" in observation.text:
            return Decision(done=True, success=True, message="new tab detail read")
        if observation.url != self.home:
            return Decision(action=Action.navigate(self.home))
        return Decision(action=Action.new_tab(self.detail), thought="open detail in a new tab")

    def _click_or_home(self, observation: Observation, name: str) -> Decision:
        target = observation.find_name(name)
        if target:
            return self._click(observation, name)
        return Decision(action=Action.navigate(self.home))

    @staticmethod
    def _click(observation: Observation, name: str) -> Decision:
        target = next((item for item in observation.elements if item.name == name), None)
        if target is None:
            return Decision(done=True, success=False, message=f"missing element: {name}")
        return Decision(action=Action.click(index=target.index, observation_id=observation.observation_id))

    @staticmethod
    def _type(index: int, observation: Observation, text: str) -> Decision:
        return Decision(action=Action.type_text(index=index, text=text, observation_id=observation.observation_id))
