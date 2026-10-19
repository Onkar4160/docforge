"""Upload type detection by content, not just extension (NFR-6)."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

from docforge.core.errors import UnsupportedFileError

MAX_ZIP_ENTRIES = 5000
MAX_ZIP_UNCOMPRESSED = 500 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200

_OOXML = {
    ".pptx": ("ppt/", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    ".potx": ("ppt/", "application/vnd.openxmlformats-officedocument.presentationml.template"),
    ".docx": ("word/", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ".dotx": ("word/", "application/vnd.openxmlformats-officedocument.wordprocessingml.template"),
    ".xlsx": ("xl/", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ".xltx": ("xl/", "application/vnd.openxmlformats-officedocument.spreadsheetml.template"),
}
_TEXT = {
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".tsv": "text/tab-separated-values",
}
_IMAGES = {
    ".png": (b"\x89PNG\r\n\x1a\n", "image/png"),
    ".jpg": (b"\xff\xd8\xff", "image/jpeg"),
    ".jpeg": (b"\xff\xd8\xff", "image/jpeg"),
}
_MACRO_PARTS = ("vbaProject.bin",)


@dataclass(frozen=True)
class FileKind:
    extension: str
    media_type: str
    family: str  # pptx | docx | xlsx | pdf | text | image

    @property
    def is_template_capable(self) -> bool:
        return self.family in ("pptx", "docx", "xlsx")


def _extension(filename: str) -> str:
    dot = filename.rfind(".")
    return filename[dot:].lower() if dot >= 0 else ""


def check_zip_safety(data: bytes) -> zipfile.ZipFile:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise UnsupportedFileError("file is not a valid Office (zip) package") from exc
    infos = zf.infolist()
    if len(infos) > MAX_ZIP_ENTRIES:
        raise UnsupportedFileError("package has too many entries")
    total = sum(i.file_size for i in infos)
    compressed = sum(i.compress_size for i in infos) or 1
    if total > MAX_ZIP_UNCOMPRESSED or total / compressed > MAX_COMPRESSION_RATIO:
        raise UnsupportedFileError("package expands beyond safe limits")
    if any(i.filename.endswith(_MACRO_PARTS) for i in infos):
        raise UnsupportedFileError("macro-enabled files are not accepted")
    return zf


def sniff(filename: str, data: bytes) -> FileKind:
    ext = _extension(filename)
    if ext in _OOXML:
        prefix, media = _OOXML[ext]
        if not data.startswith(b"PK\x03\x04"):
            raise UnsupportedFileError(f"{filename} is not a valid {ext} file")
        zf = check_zip_safety(data)
        names = zf.namelist()
        if "[Content_Types].xml" not in names or not any(n.startswith(prefix) for n in names):
            raise UnsupportedFileError(f"{filename} does not contain {ext} content")
        family = {"ppt/": "pptx", "word/": "docx", "xl/": "xlsx"}[prefix]
        return FileKind(ext, media, family)
    if ext == ".pdf":
        if not data.startswith(b"%PDF"):
            raise UnsupportedFileError(f"{filename} is not a valid PDF")
        return FileKind(ext, "application/pdf", "pdf")
    if ext in _TEXT:
        try:
            data[:65536].decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise UnsupportedFileError(f"{filename} is not UTF-8 text") from exc
        return FileKind(ext, _TEXT[ext], "text")
    if ext in _IMAGES:
        magic, media = _IMAGES[ext]
        if not data.startswith(magic):
            raise UnsupportedFileError(f"{filename} is not a valid image")
        return FileKind(ext, media, "image")
    raise UnsupportedFileError(f"unsupported file type: {ext or 'no extension'}")
