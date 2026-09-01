"""Page observation models.

Mapped from browser-use 0.13.7 SerializedDOMState / selector_map.
Indexes are valid only for one observation_id.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    x: float
    y: float
    width: float
    height: float


class InteractiveElement(BaseModel):
    index: int
    tag: str
    role: str | None = None
    name: str = ""
    field_name: str | None = None
    html_id: str | None = None
    class_name: str | None = None
    href: str | None = None
    input_type: str | None = None
    value: str | None = None
    bbox: BoundingBox | None = None

    def line(self) -> str:
        bits = [f"[{self.index}]", self.tag]
        if self.role:
            bits.append(f"role={self.role}")
        if self.input_type:
            bits.append(f"type={self.input_type}")
        if self.name:
            bits.append(f'"{self.name}"')
        if self.href:
            bits.append(self.href)
        if self.value is not None and self.value != "":
            bits.append(f"value={self.value}")
        return " ".join(bits)


class Observation(BaseModel):
    observation_id: str
    url: str
    title: str
    text: str
    elements: list[InteractiveElement] = Field(default_factory=list)
    token_estimate: int = 0

    def element(self, index: int) -> InteractiveElement | None:
        for item in self.elements:
            if item.index == index:
                return item
        return None

    def find_name(self, text: str) -> InteractiveElement | None:
        needle = text.strip()
        for item in self.elements:
            if needle in item.name:
                return item
        return None

    def summary(self, *, max_elements: int = 80) -> str:
        lines = [f"url={self.url}", f"title={self.title}", f"elements={len(self.elements)}"]
        lines.extend(item.line() for item in self.elements[:max_elements])
        return "\n".join(lines)
