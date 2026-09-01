"""Action protocol and execution results.

Mapped from browser-use 0.13.7 (MIT) ActionResult / NavigateAction / ClickElementAction.
Uses CSS selectors instead of observation indexes until stage 2.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, model_validator


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


class ErrorKind(StrEnum):
    NONE = "none"
    ELEMENT_NOT_FOUND = "element_not_found"
    TIMEOUT = "timeout"
    PAGE_CLOSED = "page_closed"
    TAB_NOT_FOUND = "tab_not_found"
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

    @model_validator(mode="after")
    def require_fields(self) -> Self:
        if self.kind is ActionKind.NAVIGATE and not self.url:
            raise ValueError("navigate requires url")
        if self.kind in {ActionKind.CLICK, ActionKind.TYPE, ActionKind.SELECT} and not self.selector:
            raise ValueError(f"{self.kind} requires selector")
        if self.kind is ActionKind.TYPE and self.text is None:
            raise ValueError("type requires text")
        if self.kind is ActionKind.SELECT and self.value is None:
            raise ValueError("select requires value")
        if self.kind is ActionKind.SWITCH_TAB and not self.tab_id:
            raise ValueError("switch_tab requires tab_id")
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
    def click(cls, selector: str, *, timeout_ms: float | None = None) -> Self:
        return cls(kind=ActionKind.CLICK, selector=selector, timeout_ms=timeout_ms)

    @classmethod
    def type_text(cls, selector: str, text: str, *, clear: bool = True, timeout_ms: float | None = None) -> Self:
        return cls(kind=ActionKind.TYPE, selector=selector, text=text, clear=clear, timeout_ms=timeout_ms)

    @classmethod
    def select(cls, selector: str, value: str, *, timeout_ms: float | None = None) -> Self:
        return cls(kind=ActionKind.SELECT, selector=selector, value=value, timeout_ms=timeout_ms)

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
