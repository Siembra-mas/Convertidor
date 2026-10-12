from pathlib import Path
import shutil

from fastapi import APIRouter, Depends, File, Response, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.core.config import Settings, get_settings
from app.core.security import validated_dicom_file
from app.services.batch_converter import convert_batch_to_zip
from app.services.dicom_converter import convert_dicom_to_png
from app.utils.files import remove_temp_file

router = APIRouter(tags=["conversion"])


@router.post("/convert", response_class=Response, responses={
    200: {"content": {"image/png": {}}},
    400: {"description": "DICOM inválido o no compatible"},
    413: {"description": "Archivo demasiado grande"},
    500: {"description": "Error interno"},
})
async def convert_dicom(
    dicom_path: Path = Depends(validated_dicom_file),
    settings: Settings = Depends(get_settings),
) -> Response:
    try:
        png_bytes = convert_dicom_to_png(dicom_path, settings)
        return Response(
            content=png_bytes,
            media_type="image/png",
            headers={"Content-Disposition": 'attachment; filename="converted.png"'},
        )
    finally:
        remove_temp_file(dicom_path)


@router.post(
    "/convert/batch",
    response_class=FileResponse,
    responses={
        200: {"content": {"application/zip": {}}},
        400: {"description": "Uno o más archivos DICOM son inválidos"},
        413: {"description": "El lote supera los límites permitidos"},
    },
)
async def convert_dicom_batch(
    files: list[UploadFile] = File(...),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    batch = await convert_batch_to_zip(files, settings)
    return FileResponse(
        path=batch.archive_path,
        media_type="application/zip",
        filename="imagenes_convertidas.zip",
        headers={"X-Processed-Files": str(batch.file_count)},
        background=BackgroundTask(shutil.rmtree, batch.directory, ignore_errors=True),
    )
