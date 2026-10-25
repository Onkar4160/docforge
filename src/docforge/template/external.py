"""Optional external design-guide extractor for PPTX templates (``PPTX_MASTERS_ENABLED``).

The built-in analyzer never depends on it. When enabled and installed, its output files are attached
to the template manifest as extra design guidance; any failure is reported and analysis continues.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from docforge.core.config import Settings
from docforge.core.logging import get_logger

log = get_logger(__name__)

MAX_OUTPUT_CHARS = 200_000


@dataclass
class ExternalGuide:
    status: str  # ok | disabled | not_installed | failed | timeout
    detail: str = ""
    files: dict[str, str] = field(default_factory=dict)  # relative name -> text content


def run_pptx_masters(settings: Settings, template: Path, output_dir: Path) -> ExternalGuide:
    if not settings.pptx_masters_enabled:
        return ExternalGuide("disabled")
    executable = shutil.which(settings.pptx_masters_command) or (
        settings.pptx_masters_command if Path(settings.pptx_masters_command).is_file() else None
    )
    if executable is None:
        return ExternalGuide("not_installed", f"'{settings.pptx_masters_command}' not found on PATH")

    output_dir.mkdir(parents=True, exist_ok=True)
    args = [
        a.format(input=str(template), output_dir=str(output_dir))
        for a in shlex.split(settings.pptx_masters_args, posix=True)
    ]
    try:
        proc = subprocess.run(  # noqa: S603 - executable and args come from operator configuration
            [executable, *args],
            capture_output=True,
            text=True,
            timeout=settings.pptx_masters_timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ExternalGuide("timeout", f"exceeded {settings.pptx_masters_timeout_s}s")
    if proc.returncode != 0:
        log.warning("pptx-masters failed rc=%s: %s", proc.returncode, proc.stderr[-500:])
        return ExternalGuide("failed", proc.stderr[-500:] or f"exit code {proc.returncode}")

    files: dict[str, str] = {}
    budget = MAX_OUTPUT_CHARS
    for path in sorted(output_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in {".json", ".md", ".txt", ".yaml", ".yml"} and budget > 0:
            text = path.read_text(encoding="utf-8", errors="replace")[:budget]
            budget -= len(text)
            files[path.relative_to(output_dir).as_posix()] = text
    if not files and proc.stdout.strip():
        files["stdout.txt"] = proc.stdout[:MAX_OUTPUT_CHARS]
    return ExternalGuide("ok", files=files)
