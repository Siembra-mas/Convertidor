import os
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.core.config import Settings
from app.core.errors import InvalidDicomError, UploadTooLargeError

DICOM_MAGIC_OFFSET = 128
DICOM_MAGIC = b"DICM"


async def save_upload_to_temp(file: UploadFile, settings: Settings) -> Path:
    """Copy in bounded chunks; never use the client-supplied filename on disk."""
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f"{uuid4().hex}_", suffix=".dcm"
    )
    temp_path = Path(temp_name)
    total_bytes = 0
    try:
        with os.fdopen(descriptor, "wb") as temp_file:
            while chunk := await file.read(settings.upload_chunk_bytes):
                total_bytes += len(chunk)
                if total_bytes > settings.max_upload_bytes:
                    raise UploadTooLargeError()
                temp_file.write(chunk)
        return temp_path
    except Exception:
        remove_temp_file(temp_path)
        raise


def validate_dicom_header(path: Path) -> None:
    # Require the Part 10 preamble marker; filename and MIME type are not trustworthy.
    with path.open("rb") as dicom_file:
        dicom_file.seek(DICOM_MAGIC_OFFSET)
        if dicom_file.read(len(DICOM_MAGIC)) != DICOM_MAGIC:
            raise InvalidDicomError("Falta el encabezado DICOM estándar (DICM).")


def remove_temp_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        # Best-effort cleanup; the generated path is never exposed to the caller.
        pass
