"""LOB Browser: a learning implementation of a reliable browser agent."""

from lob_browser.actions import Action, ActionResult, ErrorKind, run_action
from lob_browser.browser import BrowserSession, SessionConfig, SessionError

__version__ = "0.1.0"

__all__ = [
    "Action",
    "ActionResult",
    "BrowserSession",
    "ErrorKind",
    "SessionConfig",
    "SessionError",
    "run_action",
    "__version__",
]
