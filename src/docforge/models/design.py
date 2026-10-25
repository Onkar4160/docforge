from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from docforge.models.base import DFModel


class Palette(DFModel):
    """Hex colours without '#', e.g. '1F4E79'."""

    background: str = "FFFFFF"
    surface: str = "F3F4F6"
    text: str = "1F2937"
    text_muted: str = "6B7280"
    primary: str = "1F4E79"
    secondary: str = "2E75B6"
    accents: list[str] = Field(
        default_factory=lambda: ["2E75B6", "F59E0B", "10B981", "EF4444", "8B5CF6", "14B8A6"]
    )
    positive: str = "15803D"
    negative: str = "B91C1C"

    @field_validator(
        "background",
        "surface",
        "text",
        "text_muted",
        "primary",
        "secondary",
        "positive",
        "negative",
        mode="before",
    )
    @classmethod
    def _clean_color(cls, v: str) -> str:
        if isinstance(v, str):
            v = v.strip().removeprefix("#")
            if len(v) == 3:
                v = "".join(c * 2 for c in v)
            return v.upper()
        return v

    @field_validator("accents", mode="before")
    @classmethod
    def _clean_accents(cls, v: list[str]) -> list[str]:
        if isinstance(v, list):
            out = []
            for c in v:
                if isinstance(c, str):
                    c = c.strip().removeprefix("#")
                    if len(c) == 3:
                        c = "".join(ch * 2 for ch in c)
                    out.append(c.upper())
                else:
                    out.append(c)
            return out
        return v


class Fonts(DFModel):
    heading: str = "Calibri"
    body: str = "Calibri"
    mono: str = "Consolas"


class TypeScale(DFModel):
    """Point sizes per text role."""

    title: float = 40
    h1: float = 28
    h2: float = 20
    body: float = 16
    caption: float = 12
    footnote: float = 9


class Spacing(DFModel):
    margin_in: float = 0.5
    gutter_in: float = 0.25
    grid_columns: int = 12


class DesignTokens(DFModel):
    palette: Palette = Field(default_factory=Palette)
    fonts: Fonts = Field(default_factory=Fonts)
    type_scale: TypeScale = Field(default_factory=TypeScale)
    spacing: Spacing = Field(default_factory=Spacing)
    source: Literal["template", "generated", "default"] = "default"
