class AppError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class InvalidDicomError(AppError):
    def __init__(self, message: str = "El archivo no es un DICOM válido o no puede convertirse.") -> None:
        super().__init__(400, message)


class UploadTooLargeError(AppError):
    def __init__(self) -> None:
        super().__init__(413, "El archivo supera el tamaño máximo permitido de 15 MB.")


class BatchLimitError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(413, message)
