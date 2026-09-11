"""Browser session errors."""


class SessionError(Exception):
    """Browser session failed to start, connect, or stay usable."""


class SessionNotStartedError(SessionError):
    """An operation required an open session."""


class TabError(SessionError):
    """Tab create / switch / close failed."""


class TabNotFoundError(TabError):
    def __init__(self, tab_id: str) -> None:
        super().__init__(f"tab not found: {tab_id}")
        self.tab_id = tab_id


class LastTabError(TabError):
    def __init__(self) -> None:
        super().__init__("cannot close the last tab")
