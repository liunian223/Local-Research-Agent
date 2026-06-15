from __future__ import annotations

from pathlib import Path


class HarnessSecurityError(ValueError):
    pass


def ensure_inside(base_dir: Path, target: Path) -> Path:
    base = base_dir.resolve()
    resolved = target.resolve()
    if not str(resolved).startswith(str(base)):
        raise HarnessSecurityError("Path outside allowed directory.")
    return resolved


def validate_pdf_bytes(data: bytes, max_bytes: int) -> None:
    if len(data) > max_bytes:
        raise HarnessSecurityError("PDF upload exceeds size limit.")
    if not data.startswith(b"%PDF"):
        raise HarnessSecurityError("Uploaded file is not a PDF.")
