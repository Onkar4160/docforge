"""Chart images for formats without native charts in python-docx (DOCX figures)."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless, deterministic
import matplotlib.pyplot as plt  # noqa: E402

from docforge.models.ir import ChartBlock, ChartType  # noqa: E402


def chart_png(block: ChartBlock, colors: list[str], path: Path, *, font: str = "DejaVu Sans") -> Path:
    palette = [f"#{c}" for c in colors] or ["#1F4E79"]
    plt.rcParams.update({"font.family": [font, "DejaVu Sans"], "font.size": 10, "svg.hashsalt": "docforge"})
    fig, ax = plt.subplots(figsize=(6.5, 3.6), dpi=200)
    cats = block.categories
    kind = block.chart_type
    n = len(block.series)
    if kind in (ChartType.pie, ChartType.doughnut):
        wedges = ax.pie(
            block.series[0].values,
            labels=cats,
            colors=palette * 3,
            autopct="%1.0f%%",
            startangle=90,
            wedgeprops={"width": 0.45} if kind == ChartType.doughnut else None,
        )
        ax.axis("equal")
        del wedges
    elif kind in (ChartType.line, ChartType.scatter, ChartType.area):
        for i, s in enumerate(block.series):
            color = palette[i % len(palette)]
            if kind == ChartType.area:
                ax.fill_between(cats, s.values, alpha=0.35, color=color)
            ax.plot(cats, s.values, marker="o", linewidth=2, color=color, label=s.name)
    else:
        horizontal = kind in (ChartType.bar, ChartType.stacked_bar)
        stacked = kind in (ChartType.stacked_bar, ChartType.stacked_column)
        width = 0.8 if stacked else 0.8 / n
        base = [0.0] * len(cats)
        for i, s in enumerate(block.series):
            pos = (
                list(range(len(cats))) if stacked else [x - 0.4 + width * (i + 0.5) for x in range(len(cats))]
            )
            color = palette[i % len(palette)]
            if horizontal:
                bars = ax.barh(
                    pos, s.values, height=width, left=base if stacked else None, color=color, label=s.name
                )
            else:
                bars = ax.bar(
                    pos, s.values, width=width, bottom=base if stacked else None, color=color, label=s.name
                )
            if not stacked:
                ax.bar_label(bars, fmt="%g", fontsize=8, padding=2)
            if stacked:
                base = [b + v for b, v in zip(base, s.values, strict=True)]
        ticks = list(range(len(cats)))
        (ax.set_yticks if horizontal else ax.set_xticks)(ticks, cats)
    if kind not in (ChartType.pie, ChartType.doughnut):
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.grid(axis="y" if kind not in (ChartType.bar, ChartType.stacked_bar) else "x", color="#E3E6EA")
        ax.set_axisbelow(True)
        if block.unit:
            (ax.set_xlabel if kind in (ChartType.bar, ChartType.stacked_bar) else ax.set_ylabel)(block.unit)
        if n > 1:
            ax.legend(frameon=False, fontsize=9)
    if block.title:
        ax.set_title(block.title, fontsize=11, fontweight="bold", loc="left")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, format="png", metadata={"Software": None})
    plt.close(fig)
    return path
