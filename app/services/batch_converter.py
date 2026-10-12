import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from app.core.config import Settings
from app.core.errors import BatchLimitError, InvalidDicomError
from app.services.dicom_converter import convert_dicom_to_png
from app.utils.files import remove_temp_file, save_upload_to_temp, validate_dicom_header


@dataclass(frozen=True)
class BatchArchive:
    directory: Path
    archive_path: Path
    file_count: int


async def convert_batch_to_zip(
    files: list[UploadFile], settings: Settings
) -> BatchArchive:
    """Convert files serially and keep both source and archive data on disk."""
    if not files:
        raise InvalidDicomError("Selecciona al menos un archivo DICOM.")
    if len(files) > settings.max_batch_files:
        for upload in files:
            await upload.close()
        raise BatchLimitError(
            f"El lote supera el máximo de {settings.max_batch_files} archivos."
        )

    batch_directory = Path(tempfile.mkdtemp(prefix="dicom_batch_"))
    archive_path = batch_directory / "imagenes_convertidas.zip"
    total_input_bytes = 0

    try:
        with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_STORED) as archive:
            for index, upload in enumerate(files, start=1):
                dicom_path: Path | None = None
                try:
                    dicom_path = await save_upload_to_temp(upload, settings)
                    total_input_bytes += dicom_path.stat().st_size
                    if total_input_bytes > settings.max_batch_upload_bytes:
                        raise BatchLimitError(
                            "El tamaño total del lote supera el límite permitido de 512 MB."
                        )
                    try:
                        validate_dicom_header(dicom_path)
                        png_bytes = convert_dicom_to_png(dicom_path, settings)
                    except InvalidDicomError as exc:
                        raise InvalidDicomError(
                            f"El archivo número {index} no es un DICOM compatible."
                        ) from exc
                    archive.writestr(f"imagen_{index:03}.png", png_bytes)
                    del png_bytes
                    if archive.fp is not None and archive.fp.tell() > settings.max_batch_archive_bytes:
                        raise BatchLimitError(
                            "El ZIP generado supera el límite permitido de 512 MB."
                        )
                finally:
                    if dicom_path is not None:
                        remove_temp_file(dicom_path)

        return BatchArchive(
            directory=batch_directory,
            archive_path=archive_path,
            file_count=len(files),
        )
    except Exception:
        shutil.rmtree(batch_directory, ignore_errors=True)
        raise
    finally:
        for upload in files:
            await upload.close()
