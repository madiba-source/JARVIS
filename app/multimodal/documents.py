"""Explicit, local document extraction with bounded output and no auto-memory."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Callable

from .models import DocumentContent, Sensitivity


class DocumentParser:
    EXTENSIONS = {".txt", ".md", ".rst", ".py", ".js", ".ts", ".json", ".toml", ".yaml", ".yml", ".csv", ".pdf", ".png", ".jpg", ".jpeg"}

    def __init__(self, *, max_bytes: int = 1_048_576, max_chars: int = 1_048_576,
                 ocr: Callable[[bytes], str] | None = None) -> None:
        self.max_bytes = max(1024, min(max_bytes, 16_777_216))
        self.max_chars = max(1024, min(max_chars, 1_048_576))
        self.ocr = ocr

    def parse(self, path: str | Path, *, sensitivity: Sensitivity = Sensitivity.UNKNOWN) -> DocumentContent:
        source = Path(path).expanduser()
        if source.is_symlink() or not source.is_file():
            raise ValueError("document must be a regular file")
        resolved = source.resolve(strict=True)
        if resolved.stat().st_size > self.max_bytes:
            raise ValueError("document exceeds size limit")
        if resolved.suffix.lower() not in self.EXTENSIONS:
            raise ValueError("unsupported document format")
        if resolved.suffix.lower() in {".png", ".jpg", ".jpeg"}:
            if self.ocr is None:
                raise ValueError("OCR provider unavailable")
            text, metadata = self._image_ocr(resolved)
            media_type = "image/" + resolved.suffix.lower().lstrip(".")
        elif resolved.suffix.lower() == ".pdf":
            text, metadata = self._pdf(resolved)
            media_type = "application/pdf"
        else:
            raw = resolved.read_bytes()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ValueError("document is not UTF-8 text") from error
            text, metadata = self._structured(text, resolved.suffix.lower())
            media_type = "text/plain"
        text = text[:self.max_chars]
        return DocumentContent.from_text(str(resolved), text, media_type, title=resolved.name, **metadata).model_copy(update={"sensitivity": sensitivity})

    def _image_ocr(self, path: Path) -> tuple[str, dict[str, str]]:
        raw = path.read_bytes()
        try:
            text = self.ocr(raw) if self.ocr is not None else ""
        except Exception as error:
            raise ValueError("OCR extraction failed") from error
        return str(text)[:self.max_chars], {"parser": "ocr"}

    def _structured(self, text: str, suffix: str) -> tuple[str, dict[str, str]]:
        if suffix == ".csv":
            rows = list(csv.reader(io.StringIO(text)))[:512]
            return "\n".join(" | ".join(row[:64]) for row in rows), {"rows": str(len(rows)), "parser": "csv"}
        if suffix == ".json":
            try:
                return json.dumps(json.loads(text), indent=2)[:self.max_chars], {"parser": "json"}
            except json.JSONDecodeError as error:
                raise ValueError("malformed JSON document") from error
        return text, {"parser": "text"}

    def _pdf(self, path: Path) -> tuple[str, dict[str, str]]:
        try:
            from pypdf import PdfReader
        except Exception as error:
            raise ValueError("PDF parser unavailable") from error
        try:
            reader = PdfReader(str(path))
            pages = [page.extract_text() or "" for page in reader.pages[:128]]
            return "\n".join(pages), {"parser": "pypdf", "pages": str(len(pages))}
        except Exception as error:
            raise ValueError("PDF extraction failed") from error
