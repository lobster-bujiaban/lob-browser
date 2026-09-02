"""Action protocol and execution results.

Mapped from browser-use 0.13.7 (MIT) ActionResult / NavigateAction / ClickElementAction.
Uses CSS selectors instead of observation indexes until stage 2.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from lob_browser.browser.models import DialogInfo, DownloadInfo, TabInfo


class ActionKind(StrEnum):
    NAVIGATE = "navigate"
    BACK = "back"
    RELOAD = "reload"
    CLICK = "click"
    TYPE = "type"
    SELECT = "select"
    SCROLL = "scroll"
    WAIT = "wait"
    NEW_TAB = "new_tab"
    SWITCH_TAB = "switch_tab"
    CLOSE_TAB = "close_tab"
    DIALOG = "dialog"


class ErrorKind(StrEnum):
    NONE = "none"
    ELEMENT_NOT_FOUND = "element_not_found"
    TIMEOUT = "timeout"
    PAGE_CLOSED = "page_closed"
    TAB_NOT_FOUND = "tab_not_found"
    STALE_ELEMENT = "stale_element"
    DIALOG_UNHANDLED = "dialog_unhandled"
    DOWNLOAD_FAILED = "download_failed"
    UNKNOWN = "unknown"


class Action(BaseModel):
    kind: ActionKind
    url: str | None = None
    selector: str | None = None
    text: str | None = None
    value: str | None = None
    direction: Literal["up", "down"] = "down"
    amount: int | None = None
    duration_ms: float | None = None
    timeout_ms: float | None = None
    clear: bool = True
    tab_id: str | None = None
    index: int | None = None
    observation_id: str | None = None
    accept: bool | None = None
    prompt_text: str | None = None

    @model_validator(mode="after")
    def require_fields(self) -> Self:
        if self.kind is ActionKind.NAVIGATE and not self.url:
            raise ValueError("navigate requires url")
        if self.kind in {ActionKind.CLICK, ActionKind.TYPE, ActionKind.SELECT}:
            if not self.selector and self.index is None:
                raise ValueError(f"{self.kind} requires selector or index")
        if self.kind is ActionKind.TYPE and self.text is None:
            raise ValueError("type requires text")
        if self.kind is ActionKind.SELECT and self.value is None:
            raise ValueError("select requires value")
        if self.kind is ActionKind.SWITCH_TAB and not self.tab_id:
            raise ValueError("switch_tab requires tab_id")
        if self.kind is ActionKind.DIALOG and self.accept is None:
            raise ValueError("dialog requires accept")
        return self

    @classmethod
    def navigate(cls, url: str, *, timeout_ms: float | None = None) -> Self:
        return cls(kind=ActionKind.NAVIGATE, url=url, timeout_ms=timeout_ms)

    @classmethod
    def back(cls, *, timeout_ms: float | None = None) -> Self:
        return cls(kind=ActionKind.BACK, timeout_ms=timeout_ms)

    @classmethod
    def reload(cls, *, timeout_ms: float | None = None) -> Self:
        return cls(kind=ActionKind.RELOAD, timeout_ms=timeout_ms)

    @classmethod
    def click(
        cls,
        selector: str | None = None,
        *,
        index: int | None = None,
        observation_id: str | None = None,
        timeout_ms: float | None = None,
    ) -> Self:
        return cls(
            kind=ActionKind.CLICK,
            selector=selector,
            index=index,
            observation_id=observation_id,
            timeout_ms=timeout_ms,
        )

    @classmethod
    def type_text(
        cls,
        selector: str | None = None,
        text: str = "",
        *,
        index: int | None = None,
        observation_id: str | None = None,
        clear: bool = True,
        timeout_ms: float | None = None,
    ) -> Self:
        return cls(
            kind=ActionKind.TYPE,
            selector=selector,
            text=text,
            index=index,
            observation_id=observation_id,
            clear=clear,
            timeout_ms=timeout_ms,
        )

    @classmethod
    def select(
        cls,
        selector: str | None = None,
        value: str | None = None,
        *,
        index: int | None = None,
        observation_id: str | None = None,
        timeout_ms: float | None = None,
    ) -> Self:
        return cls(
            kind=ActionKind.SELECT,
            selector=selector,
            value=value,
            index=index,
            observation_id=observation_id,
            timeout_ms=timeout_ms,
        )

    @classmethod
    def scroll(
        cls,
        *,
        direction: Literal["up", "down"] = "down",
        amount: int | None = None,
        selector: str | None = None,
        timeout_ms: float | None = None,
    ) -> Self:
        return cls(
            kind=ActionKind.SCROLL,
            direction=direction,
            amount=amount,
            selector=selector,
            timeout_ms=timeout_ms,
        )

    @classmethod
    def wait(cls, duration_ms: float = 1000) -> Self:
        return cls(kind=ActionKind.WAIT, duration_ms=duration_ms)

    @classmethod
    def new_tab(cls, url: str | None = None, *, timeout_ms: float | None = None) -> Self:
        return cls(kind=ActionKind.NEW_TAB, url=url, timeout_ms=timeout_ms)

    @classmethod
    def switch_tab(cls, tab_id: str, *, timeout_ms: float | None = None) -> Self:
        return cls(kind=ActionKind.SWITCH_TAB, tab_id=tab_id, timeout_ms=timeout_ms)

    @classmethod
    def close_tab(cls, tab_id: str | None = None, *, timeout_ms: float | None = None) -> Self:
        return cls(kind=ActionKind.CLOSE_TAB, tab_id=tab_id, timeout_ms=timeout_ms)

    @classmethod
    def dialog(cls, *, accept: bool, prompt_text: str | None = None) -> Self:
        return cls(kind=ActionKind.DIALOG, accept=accept, prompt_text=prompt_text)


class PageSnapshot(BaseModel):
    url: str = ""
    title: str = ""
    summary: str = ""


class ActionResult(BaseModel):
    ok: bool
    action: Action
    error_kind: ErrorKind = ErrorKind.NONE
    error: str | None = None
    elapsed_ms: float
    before: PageSnapshot
    after: PageSnapshot
    message: str = ""
    tabs_before: list[TabInfo] = Field(default_factory=list)
    tabs_after: list[TabInfo] = Field(default_factory=list)
    opened_tabs: list[TabInfo] = Field(default_factory=list)
    switched_from_tab_id: str | None = None
    switched_to_tab_id: str | None = None
    closed_tab_id: str | None = None
    dialogs: list[DialogInfo] = Field(default_factory=list)
    downloads: list[DownloadInfo] = Field(default_factory=list)
    target_frame_path: list[int] = Field(default_factory=list)
    target_frame_url: str | None = None
    target_shadow_path: list[str] = Field(default_factory=list)
