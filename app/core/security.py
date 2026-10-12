from pathlib import Path

from fastapi import Depends, File, UploadFile
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings, get_settings
from app.core.errors import InvalidDicomError, UploadTooLargeError
from app.utils.files import remove_temp_file, save_upload_to_temp, validate_dicom_header


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; "
            "style-src 'self'; script-src 'self'; "
            "img-src 'self' blob:; connect-src 'self'; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
        )
        response.headers["Cache-Control"] = "no-store"
        return response


class RequestBodyLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        max_body_bytes: int,
        batch_max_body_bytes: int | None = None,
    ) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.batch_max_body_bytes = batch_max_body_bytes or max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return

        if scope["path"] == "/api/v1/convert":
            body_limit = self.max_body_bytes
        elif scope["path"] == "/api/v1/convert/batch":
            body_limit = self.batch_max_body_bytes
        else:
            await self.app(scope, receive, send)
            return

        content_length = next(
            (value for key, value in scope["headers"] if key.lower() == b"content-length"),
            None,
        )
        if content_length is not None:
            try:
                if int(content_length) > body_limit:
                    await self._reject(send)
                    return
            except ValueError:
                await self._reject(send)
                return

        received_bytes = 0

        async def limited_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > body_limit:
                    raise _RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _RequestBodyTooLarge:
            await self._reject(send)

    async def _reject(self, send: Send) -> None:
        body = b'{"detail":"El cuerpo de la solicitud supera el l\xc3\xadmite permitido."}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class _RequestBodyTooLarge(Exception):
    pass


async def validated_dicom_file(
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
) -> Path:
    """Stream an upload to a private temporary file and validate its DICOM marker."""
    temp_path: Path | None = None
    try:
        temp_path = await save_upload_to_temp(file, settings)
        validate_dicom_header(temp_path)
        return temp_path
    except Exception:
        if temp_path is not None:
            remove_temp_file(temp_path)
        raise
    finally:
        await file.close()
