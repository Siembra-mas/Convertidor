import os
from dataclasses import dataclass
from functools import lru_cache

DEFAULT_CORS_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")


def _positive_int_from_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{name} debe ser un entero positivo.")
    return parsed


@dataclass(frozen=True)
class Settings:
    max_upload_bytes: int = 15 * 1024 * 1024
    max_batch_upload_bytes: int = 512 * 1024 * 1024
    max_batch_files: int = 500
    max_batch_archive_bytes: int = 512 * 1024 * 1024
    upload_chunk_bytes: int = 64 * 1024
    max_decoded_samples: int = 24_000_000
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    configured_origins = os.getenv("CORS_ORIGINS")
    origins = (
        tuple(origin.strip() for origin in configured_origins.split(",") if origin.strip())
        if configured_origins is not None
        else DEFAULT_CORS_ORIGINS
    )
    return Settings(
        max_upload_bytes=_positive_int_from_env("MAX_UPLOAD_BYTES", 15 * 1024 * 1024),
        max_batch_upload_bytes=_positive_int_from_env(
            "MAX_BATCH_UPLOAD_BYTES", 512 * 1024 * 1024
        ),
        max_batch_files=_positive_int_from_env("MAX_BATCH_FILES", 500),
        max_batch_archive_bytes=_positive_int_from_env(
            "MAX_BATCH_ARCHIVE_BYTES", 512 * 1024 * 1024
        ),
        upload_chunk_bytes=_positive_int_from_env("UPLOAD_CHUNK_BYTES", 64 * 1024),
        max_decoded_samples=_positive_int_from_env(
            "MAX_DECODED_SAMPLES", 24_000_000
        ),
        cors_origins=origins,
    )
