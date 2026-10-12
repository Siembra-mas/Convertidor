from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.formparsers import MultiPartParser
from starlette.staticfiles import StaticFiles

from app.api.routes.convert import router as convert_router
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import RequestBodyLimitMiddleware, SecurityHeadersMiddleware

settings = get_settings()

# Keep large multi-file multipart submissions disk-backed instead of accumulating in RAM.
MultiPartParser.spool_max_size = 64 * 1024

app = FastAPI(title="DICOM Image Converter", version="1.0.0")
STATIC_DIRECTORY = Path(__file__).resolve().parent / "app" / "static"
FRONTEND_FILE = STATIC_DIRECTORY / "index.html"
app.add_middleware(
    RequestBodyLimitMiddleware,
    max_body_bytes=settings.max_upload_bytes + 1024 * 1024,
    batch_max_body_bytes=settings.max_batch_upload_bytes + 2 * 1024 * 1024,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.mount("/static", StaticFiles(directory=STATIC_DIRECTORY), name="static")


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(Exception)
async def unexpected_error_handler(_: Request, __: Exception) -> JSONResponse:
    # Keep internal exception details and possible patient data out of client responses.
    return JSONResponse(
        status_code=500,
        content={"detail": "Error interno al procesar la solicitud."},
    )


@app.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False, response_class=FileResponse)
async def frontend() -> FileResponse:
    return FileResponse(FRONTEND_FILE, media_type="text/html")


app.include_router(convert_router, prefix="/api/v1")
