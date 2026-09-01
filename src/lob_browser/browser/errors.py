"""Browser session errors."""


class SessionError(Exception):
    """Browser session failed to start, connect, or stay usable."""


class SessionNotStartedError(SessionError):
    """An operation required an open session."""
