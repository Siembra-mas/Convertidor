import asyncio
import os
import shutil
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
import zipfile

from fastapi import UploadFile
import numpy as np
from PIL import Image
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.pixels import compress
from pydicom.uid import ExplicitVRLittleEndian, RLELossless, SecondaryCaptureImageStorage, generate_uid

from app.core.config import Settings
from app.core.errors import BatchLimitError, InvalidDicomError, UploadTooLargeError
from app.core.security import RequestBodyLimitMiddleware
from app.services.batch_converter import convert_batch_to_zip
from app.services.dicom_converter import _prepare_png_samples, convert_dicom_to_png
from app.utils.files import save_upload_to_temp, validate_dicom_header


class DicomUploadSecurityTests(unittest.TestCase):
    def test_auto_contrast_expands_narrow_grayscale_range(self) -> None:
        pixels = np.array([[100, 101], [102, 103]], dtype=np.uint8)

        rendered, bit_depth = _prepare_png_samples(
            pixels,
            bits_stored=8,
            pixel_representation=0,
            photometric="MONOCHROME2",
            display_range=None,
        )

        self.assertEqual(bit_depth, 8)
        self.assertEqual(int(rendered.min()), 0)
        self.assertEqual(int(rendered.max()), 255)
        self.assertTrue(np.all(np.diff(rendered.ravel()) > 0))

    def test_batch_limit_is_500_and_rejects_the_501st_file(self) -> None:
        settings = Settings()
        files = [
            UploadFile(filename=f"{index}.dcm", file=BytesIO())
            for index in range(settings.max_batch_files + 1)
        ]
        self.assertEqual(settings.max_batch_files, 500)
        with self.assertRaises(BatchLimitError):
            asyncio.run(convert_batch_to_zip(files, settings))

    def test_body_limit_rejects_chunked_request_without_content_length(self) -> None:
        async def exercise(path: str, batch_limit: int) -> list[dict[str, object]]:
            messages = [
                {"type": "http.request", "body": b"123", "more_body": True},
                {"type": "http.request", "body": b"45", "more_body": False},
            ]
            responses: list[dict[str, object]] = []

            async def receive() -> dict[str, object]:
                return messages.pop(0)

            async def send(message: dict[str, object]) -> None:
                responses.append(message)

            async def consume_body(scope, receive, send) -> None:
                while (await receive()).get("more_body"):
                    pass
                await send({"type": "http.response.start", "status": 200, "headers": []})
                await send({"type": "http.response.body", "body": b"ok"})

            scope = {
                "type": "http",
                "method": "POST",
                "path": path,
                "headers": [],
            }
            await RequestBodyLimitMiddleware(
                consume_body,
                max_body_bytes=10,
                batch_max_body_bytes=batch_limit,
            )(scope, receive, send)
            return responses

        batch_responses = asyncio.run(exercise("/api/v1/convert/batch", batch_limit=4))
        regular_responses = asyncio.run(exercise("/api/v1/convert", batch_limit=4))
        self.assertEqual(batch_responses[0]["status"], 413)
        self.assertEqual(regular_responses[0]["status"], 200)

    def test_requires_standard_dicom_marker_at_offset_128(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.dcm"
            path.write_bytes(b"\0" * 128 + b"DICM" + b"data")
            validate_dicom_header(path)
            path.write_bytes(b"\0" * 128 + b"NOPE" + b"data")
            with self.assertRaises(InvalidDicomError):
                validate_dicom_header(path)

    def test_upload_is_rejected_over_configured_limit(self) -> None:
        settings = Settings(max_upload_bytes=4, upload_chunk_bytes=2)
        upload = UploadFile(filename="../../untrusted.dcm", file=tempfile.SpooledTemporaryFile())
        upload.file.write(b"12345")
        upload.file.seek(0)
        self.addCleanup(upload.file.close)
        with tempfile.TemporaryDirectory() as directory:
            temp_path = Path(directory) / "generated.dcm"
            descriptor = os.open(temp_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            with patch("app.utils.files.tempfile.mkstemp", return_value=(descriptor, str(temp_path))):
                with self.assertRaises(UploadTooLargeError):
                    asyncio.run(save_upload_to_temp(upload, settings))
                self.assertFalse(temp_path.exists())

    def test_conversion_emits_lossless_png_without_dicom_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.dcm"
            file_meta = FileMetaDataset()
            file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
            file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
            file_meta.MediaStorageSOPInstanceUID = generate_uid()
            dataset = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
            dataset.SOPClassUID = SecondaryCaptureImageStorage
            dataset.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
            dataset.PatientName = "PHI MUST NOT APPEAR"
            dataset.Rows = 2
            dataset.Columns = 2
            dataset.SamplesPerPixel = 1
            dataset.PhotometricInterpretation = "MONOCHROME2"
            dataset.BitsAllocated = 16
            dataset.BitsStored = 12
            dataset.HighBit = 11
            dataset.PixelRepresentation = 0
            dataset.WindowCenter = 2048
            dataset.WindowWidth = 4096
            dataset.PixelData = np.array([[0, 1], [2048, 4095]], dtype=np.uint16).tobytes()
            dataset.save_as(path)

            png = convert_dicom_to_png(path, Settings())

        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertNotIn(b"PHI MUST NOT APPEAR", png)
        with Image.open(BytesIO(png)) as image:
            self.assertEqual(image.size, (2, 2))
            self.assertEqual(image.format, "PNG")
            samples = np.asarray(image)
            self.assertEqual(int(samples.min()), 0)
            self.assertEqual(int(samples.max()), 65535)
            self.assertTrue(np.all(np.diff(samples.ravel()) > 0))
            self.assertEqual(len(image.getexif()), 0)

    def test_unsupported_pixel_decoder_returns_client_error(self) -> None:
        class UnavailableDecoderDataset:
            Rows = 1
            Columns = 1
            BitsStored = 8
            PixelRepresentation = 0
            PhotometricInterpretation = "MONOCHROME2"

            def __contains__(self, key: str) -> bool:
                return key == "PixelData"

            def clear(self) -> None:
                pass

            @property
            def pixel_array(self) -> np.ndarray:
                raise RuntimeError("decoder plugin unavailable")

        with patch(
            "app.services.dicom_converter.pydicom.dcmread",
            return_value=UnavailableDecoderDataset(),
        ):
            with self.assertRaisesRegex(InvalidDicomError, "códec compatible"):
                convert_dicom_to_png(Path("unavailable-codec.dcm"), Settings())

    def test_batch_converts_files_sequentially_and_uses_generic_zip_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            uploads = []
            for index in range(2):
                path = Path(directory) / f"patient-{index}.dcm"
                file_meta = FileMetaDataset()
                file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
                file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
                file_meta.MediaStorageSOPInstanceUID = generate_uid()
                dataset = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
                dataset.SOPClassUID = SecondaryCaptureImageStorage
                dataset.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
                dataset.PatientName = f"PatientPHI{index}"
                dataset.Rows = dataset.Columns = 16
                dataset.SamplesPerPixel = 1
                dataset.PhotometricInterpretation = "MONOCHROME2"
                dataset.BitsAllocated = dataset.BitsStored = 8
                dataset.HighBit = 7
                dataset.PixelRepresentation = 0
                pixels = np.arange(256, dtype=np.uint8).reshape(16, 16)
                dataset.PixelData = pixels.tobytes()
                if index == 1:
                    compress(dataset, RLELossless, arr=pixels)
                dataset.save_as(path)
                uploads.append(UploadFile(filename=f"patient-{index}.dcm", file=path.open("rb")))

            batch = asyncio.run(convert_batch_to_zip(uploads, Settings()))
            try:
                with zipfile.ZipFile(batch.archive_path) as archive:
                    self.assertEqual(
                        archive.namelist(), ["imagen_001.png", "imagen_002.png"]
                    )
                    image_bytes = [archive.read(name) for name in archive.namelist()]
                self.assertEqual(batch.file_count, 2)
                self.assertTrue(all(image.startswith(b"\x89PNG\r\n\x1a\n") for image in image_bytes))
                self.assertNotIn(b"PatientPHI", batch.archive_path.read_bytes())
            finally:
                shutil.rmtree(batch.directory, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
