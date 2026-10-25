"""Citation numbering and reference formatting shared by document renderers (ADR-006)."""

from __future__ import annotations

import re
from collections.abc import Iterable

from docforge.models.evidence import ResearchDossier, Source
from docforge.models.intent import CitationStyle


class Citations:
    """Maps claim ids to sources and produces in-text markers and the reference list."""

    def __init__(self, dossier: ResearchDossier | None, style: CitationStyle) -> None:
        self.style = style
        self.dossier = dossier
        self._numbers: dict[str, int] = {}
        if dossier:
            self._src = {s.id: s for s in dossier.sources}
            self._evd = {e.id: e.source_id for e in dossier.evidence}
            self._claims = {c.id: c for c in dossier.claims}
        else:
            self._src, self._evd, self._claims = {}, {}, {}

    def sources_for(self, claim_ids: Iterable[str]) -> list[Source]:
        out: list[Source] = []
        for cid in claim_ids:
            claim = self._claims.get(cid)
            for eid in claim.evidence_ids if claim else []:
                src = self._src.get(self._evd.get(eid, ""))
                if src and src not in out:
                    out.append(src)
        return out

    def marker(self, claim_ids: Iterable[str]) -> str:
        """In-text citation for the given claims, registering sources in order of first use."""
        sources = self.sources_for(claim_ids)
        if not sources or self.style == CitationStyle.none:
            return ""
        for s in sources:
            self._numbers.setdefault(s.id, len(self._numbers) + 1)
        if self.style == CitationStyle.numeric:
            return " [" + ", ".join(str(self._numbers[s.id]) for s in sources) + "]"
        sep = ", " if self.style == CitationStyle.apa else " "
        return " (" + "; ".join(f"{_short_author(s)}{sep}{_year(s)}" for s in sources) + ")"

    @property
    def cited(self) -> list[Source]:
        ordered = sorted(self._numbers.items(), key=lambda kv: kv[1])
        sources = [self._src[sid] for sid, _ in ordered]
        if self.style in (CitationStyle.apa, CitationStyle.harvard):
            sources.sort(key=lambda s: (_short_author(s).lower(), _year(s)))
        return sources

    def reference_entries(self) -> list[str]:
        entries = []
        for s in self.cited:
            authors = s.author or s.publisher or "Unknown author"
            title = s.title.rstrip(".")
            venue = s.venue or (s.publisher if s.publisher != authors else None)
            link = f"https://doi.org/{s.doi.removeprefix('https://doi.org/')}" if s.doi else (s.url or "")
            if self.style == CitationStyle.numeric:
                parts = [f"[{self._numbers[s.id]}] {authors}", title, venue, _year(s), link]
                entries.append(". ".join(p for p in parts if p))
            elif self.style == CitationStyle.apa:
                entries.append(
                    f"{authors} ({_year(s)}). {title}."
                    + (f" {venue}." if venue else "")
                    + (f" {link}" if link else "")
                )
            else:  # harvard
                entries.append(
                    f"{authors} ({_year(s)}) {title}."
                    + (f" {venue}." if venue else "")
                    + (f" Available at: {link}" if link else "")
                )
        return entries


def _year(s: Source) -> str:
    m = re.match(r"(\d{4})", s.published_at or "")
    return m.group(1) if m else "n.d."


def _short_author(s: Source) -> str:
    if s.author:
        first = s.author.split(",")[0].strip()
        surname = first.split()[-1] if first.split() else first
        return f"{surname} et al." if "," in s.author or "et al" in s.author else surname
    return s.publisher or "Anon."
