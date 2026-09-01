"""Action execution errors."""

from __future__ import annotations


class ActionError(Exception):
    """A browser action failed in a classified way."""


class ElementNotFoundError(ActionError):
    def __init__(self, selector: str) -> None:
        super().__init__(f"element not found: {selector}")
        self.selector = selector


class ActionTimeoutError(ActionError):
    """The action exceeded its timeout."""


class PageClosedError(ActionError):
    """The target page was closed before or during the action."""


class StaleElementError(ActionError):
    """An element index is not valid for the current observation."""
