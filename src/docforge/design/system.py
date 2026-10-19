"""Design tokens for output without a template (FR-PPTX-3).

Palettes are content-informed: the planner may name one (``DeckPlan.design_hint``); otherwise topic
and tone keywords pick one, with a stable hash as the final tie-breaker so reruns look the same.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from docforge.models.design import DesignTokens, Fonts, Palette, Spacing, TypeScale


@dataclass(frozen=True)
class NamedPalette:
    name: str
    dark: str  # backgrounds of title/section/closing slides
    primary: str
    secondary: str
    accent: str
    surface: str  # card tint on light slides
    keywords: tuple[str, ...]


PALETTES: dict[str, NamedPalette] = {
    p.name: p
    for p in (
        NamedPalette(
            "midnight_executive",
            "1E2761",
            "1E2761",
            "4A5FC1",
            "F2A541",
            "EEF1FB",
            ("board", "executive", "strategy", "investor", "finance", "bank", "corporate", "quarterly"),
        ),
        NamedPalette(
            "forest_moss",
            "1F3D20",
            "2C5F2D",
            "97BC62",
            "E0A526",
            "EFF5E8",
            ("sustainab", "climate", "forest", "agricultur", "environment", "green", "nature", "esg"),
        ),
        NamedPalette(
            "coral_energy",
            "2F3C7E",
            "F96167",
            "2F3C7E",
            "F9C74F",
            "FEF0F0",
            ("marketing", "launch", "brand", "campaign", "startup", "creative", "consumer"),
        ),
        NamedPalette(
            "warm_terracotta",
            "5A2A22",
            "B85042",
            "A7BEAE",
            "D9A441",
            "F8EFEA",
            ("culture", "history", "architecture", "food", "travel", "heritage", "craft"),
        ),
        NamedPalette(
            "ocean_depth",
            "0B2545",
            "065A82",
            "1C7293",
            "F4A259",
            "E8F2F7",
            ("ocean", "water", "maritime", "logistics", "shipping", "energy", "charging", "electric"),
        ),
        NamedPalette(
            "charcoal_minimal",
            "212121",
            "36454F",
            "6B7B86",
            "E4572E",
            "F2F2F2",
            ("technical", "engineering", "software", "architecture review", "security", "data", "ai"),
        ),
        NamedPalette(
            "teal_trust",
            "023E46",
            "028090",
            "00A896",
            "F0B429",
            "E6F6F4",
            ("health", "medical", "clinical", "pharma", "care", "hospital", "wellness", "biotech"),
        ),
        NamedPalette(
            "berry_cream",
            "3E1A2A",
            "6D2E46",
            "A26769",
            "D4A373",
            "F6EEF0",
            ("fashion", "beauty", "luxury", "retail", "hospitality", "event"),
        ),
        NamedPalette(
            "cherry_bold",
            "2F3C7E",
            "990011",
            "2F3C7E",
            "F4B942",
            "FBEDEE",
            ("risk", "urgent", "crisis", "competition", "sales", "growth", "performance"),
        ),
    )
}


def _choose(text: str, hint: str | None) -> NamedPalette:
    if hint and hint in PALETTES:
        return PALETTES[hint]
    lowered = text.lower()
    best, best_score = None, 0
    for palette in PALETTES.values():
        score = sum(len(re.findall(r"\b" + re.escape(k), lowered)) for k in palette.keywords)
        if score > best_score:
            best, best_score = palette, score
    if best is not None:
        return best
    names = sorted(PALETTES)
    digest = int(hashlib.sha256(lowered.encode()).hexdigest(), 16)
    return PALETTES[names[digest % len(names)]]


def generated_tokens(topic_text: str, *, tone: str = "", hint: str | None = None) -> DesignTokens:
    p = _choose(f"{topic_text} {tone}", hint)
    return DesignTokens(
        palette=Palette(
            background="FFFFFF",
            surface=p.surface,
            text="1F2328",
            text_muted="5B6470",
            primary=p.primary,
            secondary=p.secondary,
            accents=[p.primary, p.secondary, p.accent, "5B6470", p.dark],
            positive="2E7D32",
            negative="C62828",
        ),
        # Cambria headings + Calibri body: ship with Office and have metric-compatible substitutes.
        fonts=Fonts(heading="Cambria", body="Calibri", mono="Courier New"),
        type_scale=TypeScale(title=44, h1=30, h2=20, body=16, caption=12, footnote=10),
        spacing=Spacing(margin_in=0.6, gutter_in=0.35, grid_columns=12),
        source="generated",
    )


def dark_color(tokens: DesignTokens) -> str:
    """Background for title/section/closing slides (last accent slot holds the palette's dark tone)."""
    return tokens.palette.accents[-1] if tokens.palette.accents else tokens.palette.primary


def palette_names() -> list[str]:
    return sorted(PALETTES)


def relative_luminance(hex_color: str) -> float:
    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (0, 2, 4))

    def chan(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast_ratio(a: str, b: str) -> float:
    la, lb = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def readable_on(background: str, light: str = "FFFFFF", dark: str = "1F2328") -> str:
    return light if contrast_ratio(background, light) >= contrast_ratio(background, dark) else dark


def tint(hex_color: str, amount: float) -> str:
    """Mix a colour with white; amount 0 = unchanged, 1 = white."""
    rgb = [int(hex_color[i : i + 2], 16) for i in (0, 2, 4)]
    return "".join(f"{round(c + (255 - c) * amount):02X}" for c in rgb)


def tokens_from_theme(theme, topic_text: str) -> DesignTokens:
    """Design tokens taken from a template theme (FR-TPL-7); generated tokens when the theme is unreadable."""
    colors = theme.colors
    if not colors.get("accent1"):
        tokens = generated_tokens(topic_text)
        if theme.major_font or theme.minor_font:
            tokens.fonts = Fonts(
                heading=theme.major_font or tokens.fonts.heading, body=theme.minor_font or tokens.fonts.body
            )
        return tokens
    background = colors.get("lt1", "FFFFFF")
    text = colors.get("dk1", "1F2328")
    dark = colors.get("dk2") or text
    accents = [
        colors[k] for k in ("accent1", "accent2", "accent3", "accent4", "accent5", "accent6") if k in colors
    ]
    # Primary must be readable on the background (headings and figures use it).
    readable = [a for a in accents if contrast_ratio(a, background) >= 3.0]
    primary = readable[0] if readable else dark
    secondary = next((a for a in readable[1:]), accents[1] if len(accents) > 1 else primary)
    return DesignTokens(
        palette=Palette(
            background=background,
            surface=tint(primary, 0.9),
            text=text,
            text_muted=colors.get("dk2", "5B6470")
            if contrast_ratio(colors.get("dk2", "5B6470"), background) >= 4.5
            else "5B6470",
            primary=primary,
            secondary=secondary,
            accents=[primary, secondary, *(a for a in accents if a not in (primary, secondary))][:4] + [dark],
        ),
        fonts=Fonts(
            heading=theme.major_font or "Calibri", body=theme.minor_font or "Calibri", mono="Courier New"
        ),
        type_scale=TypeScale(title=44, h1=30, h2=20, body=16, caption=12, footnote=10),
        spacing=Spacing(margin_in=0.6, gutter_in=0.35, grid_columns=12),
        source="template",
    )


def darken_until(hex_color: str, background: str, target: float) -> str:
    """Darken a colour in small steps until it reaches ``target`` contrast on ``background``."""
    rgb = [int(hex_color[i : i + 2], 16) for i in (0, 2, 4)]
    for _ in range(20):
        candidate = "".join(f"{c:02X}" for c in rgb)
        if contrast_ratio(candidate, background) >= target:
            return candidate
        rgb = [round(c * 0.88) for c in rgb]
    return "".join(f"{c:02X}" for c in rgb)


def tokens_from_template(manifest, topic_text: str) -> DesignTokens:
    """PPTX template tokens: from the slide artwork when the design lives on the slides, else the theme."""
    info = manifest.pptx
    base = tokens_from_theme(manifest.theme, topic_text)
    if info is None or info.design_mode != "slides":
        return base
    # Content sits on the light areas of the designed slides; colours must contrast with that colour.
    regions = [b.region_color for b in info.slide_bases if b.kind == "content" and b.region_color]
    light = [c for c in regions if contrast_ratio(c, "000000") >= 10]
    background = max(set(light), key=light.count) if light else "FFFFFF"
    text = info.slide_text_color or base.palette.text
    if contrast_ratio(text, background) < 4.5:
        text = "1F2328"

    def readable(color: str) -> str:
        for bg in set(light) | {background}:
            color = darken_until(color, bg, 3.2)
        return color

    accents = [readable(a) for a in info.slide_palette] or [base.palette.primary]
    primary = accents[0]
    secondary = accents[1] if len(accents) > 1 else readable(tint(primary, 0.3))
    muted = darken_until("5B6470", background, 4.5)
    return DesignTokens(
        palette=Palette(
            background=background,
            surface=tint(primary, 0.88),
            text=text,
            text_muted=muted,
            primary=primary,
            secondary=secondary,
            accents=[primary, secondary, *accents[2:4], text][:5],
        ),
        fonts=Fonts(
            heading=info.slide_fonts.get("heading") or base.fonts.heading,
            body=info.slide_fonts.get("body") or base.fonts.body,
            mono="Courier New",
        ),
        type_scale=base.type_scale,
        spacing=base.spacing,
        source="template",
    )
