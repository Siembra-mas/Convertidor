from io import BytesIO
from pathlib import Path

import numpy as np
import pydicom
import png
from pydicom.errors import InvalidDicomError as PydicomInvalidDicomError
from pydicom.pixels import apply_modality_lut, apply_voi_lut

from app.core.config import Settings
from app.core.errors import InvalidDicomError


def convert_dicom_to_png(path: Path, settings: Settings) -> bytes:
    """Decode pixels only, discard the DICOM dataset, and emit metadata-free PNG."""
    dataset = None
    pixels: np.ndarray | None = None
    bits_stored = 0
    pixel_representation = 0
    display_range: tuple[float, float] | None = None
    try:
        dataset = pydicom.dcmread(path, force=False)
        rows = int(dataset.Rows)
        columns = int(dataset.Columns)
        frames = int(getattr(dataset, "NumberOfFrames", 1))
        samples_per_pixel = int(getattr(dataset, "SamplesPerPixel", 1))
        bits_stored = int(dataset.BitsStored)
        pixel_representation = int(getattr(dataset, "PixelRepresentation", 0))
        photometric = str(getattr(dataset, "PhotometricInterpretation", "MONOCHROME2"))

        if rows < 1 or columns < 1 or frames < 1 or samples_per_pixel not in (1, 3):
            raise InvalidDicomError()
        if bits_stored < 1 or bits_stored > 16 or pixel_representation not in (0, 1):
            raise InvalidDicomError("La profundidad de píxel DICOM no es compatible con PNG.")
        if rows * columns * frames * samples_per_pixel > settings.max_decoded_samples:
            raise InvalidDicomError("La imagen DICOM excede el límite de píxeles procesable.")
        if "PixelData" not in dataset:
            raise InvalidDicomError("El DICOM no contiene datos de imagen.")

        try:
            pixels = dataset.pixel_array
            if samples_per_pixel == 1:
                pixels = apply_modality_lut(pixels, dataset)
                has_voi_lut = bool(dataset.get("VOILUTSequence"))
                has_window = (
                    dataset.get("WindowCenter") is not None
                    and dataset.get("WindowWidth") is not None
                )
                if has_voi_lut or has_window:
                    pixels = apply_voi_lut(pixels, dataset)
                    display_range = _voi_output_range(
                        dataset,
                        bits_stored,
                        pixel_representation,
                    )
        except (RuntimeError, NotImplementedError) as exc:
            raise InvalidDicomError(
                "No se pudo decodificar la compresión DICOM; puede faltar un códec compatible."
            ) from exc
    except InvalidDicomError:
        raise
    except (PydicomInvalidDicomError, AttributeError, KeyError, TypeError, ValueError, OverflowError) as exc:
        raise InvalidDicomError() from exc
    finally:
        # pydicom's dataset contains patient metadata; retain only the decoded pixel matrix.
        if dataset is not None:
            dataset.clear()
            del dataset

    if pixels is None:
        raise InvalidDicomError()

    if frames > 1:
        pixels = pixels[0]
    samples, bit_depth = _prepare_png_samples(
        pixels,
        bits_stored,
        pixel_representation,
        photometric,
        display_range,
    )
    if samples.ndim == 2:
        height, width = samples.shape
        greyscale = True
    elif samples.ndim == 3 and samples.shape[-1] == 3:
        height, width, _ = samples.shape
        greyscale = False
    else:
        raise InvalidDicomError("El formato de píxeles DICOM no es compatible.")

    output = BytesIO()
    writer = png.Writer(
        width=width,
        height=height,
        greyscale=greyscale,
        bitdepth=bit_depth,
        compression=6,
    )
    rows = samples.reshape(height, -1)
    writer.write(output, (row for row in rows))
    return output.getvalue()


def _prepare_png_samples(
    pixels: np.ndarray,
    bits_stored: int,
    pixel_representation: int,
    photometric: str,
    display_range: tuple[float, float] | None,
) -> tuple[np.ndarray, int]:
    bit_depth = 8 if bits_stored <= 8 else 16
    output_dtype = np.uint8 if bit_depth == 8 else np.uint16
    shift = bit_depth - bits_stored

    if pixels.ndim == 2:
        values = pixels.astype(np.float64, copy=False)
        if display_range is None:
            low, high = np.percentile(values, (1, 99))
        else:
            low, high = display_range

        if not np.isfinite(low) or not np.isfinite(high) or high <= low:
            samples = np.full(pixels.shape, np.iinfo(output_dtype).max // 2, dtype=output_dtype)
        else:
            maximum = np.iinfo(output_dtype).max
            normalized = np.clip((values - low) / (high - low), 0, 1)
            samples = np.rint(normalized * maximum).astype(output_dtype)
        if photometric == "MONOCHROME1":
            np.subtract(np.iinfo(output_dtype).max, samples, out=samples)
        return samples, bit_depth

    if pixel_representation:
        minimum = -(1 << (bits_stored - 1))
        maximum = (1 << (bits_stored - 1)) - 1
        if pixels.min() < minimum or pixels.max() > maximum:
            raise InvalidDicomError("Los valores de píxel exceden BitsStored.")
        samples = pixels.astype(output_dtype, copy=True)
        np.add(samples, 1 << (bits_stored - 1), out=samples, casting="unsafe")
    else:
        maximum = (1 << bits_stored) - 1
        if pixels.min() < 0 or pixels.max() > maximum:
            raise InvalidDicomError("Los valores de píxel exceden BitsStored.")
        samples = pixels.astype(output_dtype, copy=True)

    if shift:
        np.left_shift(samples, shift, out=samples)
    return samples, bit_depth


def _voi_output_range(
    dataset: pydicom.Dataset,
    bits_stored: int,
    pixel_representation: int,
) -> tuple[float, float]:
    voi_luts = dataset.get("VOILUTSequence")
    if voi_luts:
        lut_descriptor = voi_luts[0].LUTDescriptor
        output_bits = int(lut_descriptor[2])
        return 0.0, float((1 << output_bits) - 1)

    if pixel_representation:
        low = float(-(1 << (bits_stored - 1)))
        high = float((1 << (bits_stored - 1)) - 1)
    else:
        low = 0.0
        high = float((1 << bits_stored) - 1)

    slope = dataset.get("RescaleSlope")
    intercept = dataset.get("RescaleIntercept")
    if slope is not None and intercept is not None:
        low = low * float(slope) + float(intercept)
        high = high * float(slope) + float(intercept)
    return low, high
