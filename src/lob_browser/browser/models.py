"""Public snapshots for a browser session."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class SessionConfig(BaseModel):
    """How a session should attach to Chromium."""

    headless: bool = True
    cdp_url: str | None = None
    timeout_ms: float = 30_000
    viewport_width: int = 1280
    viewport_height: int = 720
    artifact_dir: Path = Path("artifacts")
    upload_roots: list[Path] = Field(default_factory=list)
    max_upload_bytes: int = 10 * 1024 * 1024


class TabInfo(BaseModel):
    tab_id: str
    url: str = "about:blank"
    title: str = ""
    current: bool = False


class DialogInfo(BaseModel):
    type: str
    message: str
    default_value: str = ""
    accepted: bool
    prompt_text: str | None = None
    configured: bool = False


class DownloadInfo(BaseModel):
    url: str
    suggested_filename: str
    saved_path: str | None = None
    size: int | None = None
    sha256: str | None = None
    failure: str | None = None


class UploadInfo(BaseModel):
    path: str
    filename: str
    size: int
    sha256: str


class SessionInfo(BaseModel):
    session_id: str
    started: bool
    owns_browser: bool
    cdp_url: str | None = None
    context_id: str | None = None
    current_tab_id: str | None = None
    tabs: list[TabInfo] = Field(default_factory=list)
