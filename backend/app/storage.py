from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from fastapi import UploadFile

from .config import get_settings


class PdfValidationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def upload_path(document_id: str) -> Path:
    return get_settings().upload_dir / f"{document_id}.pdf"


def save_upload(document_id: str, upload: UploadFile) -> tuple[Path, int, str]:
    """Store the uploaded PDF after cheap validation. Deep validation happens in the worker."""
    settings = get_settings()
    limit = settings.max_upload_mb * 1024 * 1024
    target = upload_path(document_id)
    digest = hashlib.sha256()
    total = 0
    head = b""

    upload.file.seek(0)
    with target.open("wb") as out:
        while True:
            piece = upload.file.read(1024 * 1024)
            if not piece:
                break
            if not head:
                head = piece[:1024]
            total += len(piece)
            if total > limit:
                out.close()
                target.unlink(missing_ok=True)
                raise PdfValidationError(
                    "too_large", f"File exceeds the {settings.max_upload_mb} MB limit"
                )
            digest.update(piece)
            out.write(piece)

    if total == 0:
        target.unlink(missing_ok=True)
        raise PdfValidationError("empty_file", "The uploaded file is empty")
    if b"%PDF-" not in head:
        target.unlink(missing_ok=True)
        raise PdfValidationError("not_pdf", "The file does not have a valid PDF signature")

    return target, total, digest.hexdigest()


def delete_file(document_id: str) -> None:
    upload_path(document_id).unlink(missing_ok=True)


def page_cache_dir(document_id: str) -> Path:
    path = get_settings().data_dir / "pagecache" / document_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def clear_page_cache(document_id: str) -> None:
    shutil.rmtree(get_settings().data_dir / "pagecache" / document_id, ignore_errors=True)
