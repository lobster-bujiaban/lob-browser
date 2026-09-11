"""LOB Browser: a learning implementation of a reliable browser agent."""

from lob_browser.actions import Action, ActionResult, ErrorKind, run_action
from lob_browser.agent import AgentResult, ScriptedDecider, run_task
from lob_browser.browser import BrowserSession, SessionConfig, SessionError
from lob_browser.observation import Observation, observe

__version__ = "0.1.0"

__all__ = [
    "Action",
    "ActionResult",
    "BrowserSession",
    "ErrorKind",
    "AgentResult",
    "Observation",
    "ScriptedDecider",
    "SessionConfig",
    "SessionError",
    "observe",
    "run_action",
    "run_task",
    "__version__",
]
