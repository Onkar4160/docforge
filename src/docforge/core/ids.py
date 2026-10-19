"""Sortable, prefixed identifiers (``ses_01J...``): 48-bit ms timestamp + 80 random bits, Crockford base32."""

from __future__ import annotations

import secrets
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

PREFIXES = {
    "session": "ses",
    "message": "msg",
    "file": "fil",
    "task": "tsk",
    "job": "job",
    "artifact": "art",
    "interpretation": "int",
    "dossier": "dos",
    "source": "src",
    "evidence": "evd",
    "claim": "clm",
    "template": "tpl",
    "report": "qr",
    "finding": "fnd",
    "llmcall": "llm",
}


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        value, rem = divmod(value, 32)
        chars.append(_ALPHABET[rem])
    return "".join(reversed(chars))


def new_id(kind: str) -> str:
    prefix = PREFIXES.get(kind, kind)
    ts = int(time.time() * 1000) & ((1 << 48) - 1)
    rand = secrets.randbits(80)
    return f"{prefix}_{_encode(ts, 10)}{_encode(rand, 16)}"
