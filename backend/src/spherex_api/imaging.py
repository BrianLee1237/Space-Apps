"""Inspect named MEF planes and render registered, explicitly quick-look PNGs."""

import hashlib
import io
import re
import warnings
from pathlib import Path

import astropy.units as u
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS
from PIL import Image
from scipy.ndimage import map_coordinates

from .archive import ArchiveError
from .models import SearchRequest


def finite_float(value):
    try:
        result = float(value)
        return result if np.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def spatial_wcs(header):
    result = WCS(header).celestial
    if not result.has_celestial:
        raise ArchiveError("Science IMAGE has no celestial WCS")
    return result


def inspect_fits(source: Path | io.BytesIO, request: SearchRequest):
    try:
        with fits.open(source, memmap=False) as hdus:
            required = ("IMAGE", "FLAGS", "VARIANCE", "ZODI", "WCS-WAVE")
            if any(name not in hdus for name in required):
                raise ArchiveError("Cutout is missing a required named FITS extension")
            image = np.asarray(hdus["IMAGE"].data)
            if image.ndim != 2 or image.size == 0:
                raise ArchiveError("Expected a nonempty two-dimensional IMAGE plane")
            for name in ("FLAGS", "VARIANCE", "ZODI"):
                if hdus[name].data.shape != image.shape:
                    raise ArchiveError(f"{name} does not match the IMAGE shape")
            header = hdus["IMAGE"].header
            celestial = spatial_wcs(header)
            coord = SkyCoord(request.ra, request.dec, unit="deg", frame="icrs")
            x, y = (float(value) for value in celestial.world_to_pixel(coord))
            inside = bool(
                np.isfinite(x)
                and np.isfinite(y)
                and 0 <= x <= image.shape[1] - 1
                and 0 <= y <= image.shape[0] - 1
            )
            # Spectral WCS uses detector/filter geometry; SIP applies only to sky WCS.
            spectral_header = header.copy()
            for keyword in list(spectral_header):
                if re.fullmatch(r"(A|B|AP|BP)_(ORDER|\d+_\d+)", keyword):
                    del spectral_header[keyword]
            spectral = WCS(spectral_header, fobj=hdus, key="W")
            spectral.sip = None
            yy, xx = np.indices(image.shape)
            wavelength, bandwidth = spectral.pixel_to_world(xx, yy)
            wave = wavelength.to_value(u.um)
            center_wave = center_width = None
            if inside:
                cw, cb = spectral.pixel_to_world(float(x), float(y))
                center_wave = finite_float(cw.to_value(u.um))
                center_width = finite_float(cb.to_value(u.um))
            flags = np.asarray(hdus["FLAGS"].data, dtype=np.uint32)
            flag_header = hdus["FLAGS"].header
            flag_definitions = {}
            for keyword in flag_header:
                match = re.fullmatch(r"MSKN(\d{4})", keyword)
                if match:
                    bit = int(match[1])
                    flag_definitions[str(bit)] = {
                        "name": str(flag_header[keyword]),
                        "description": str(flag_header.get("MSKD" + match[1], "")),
                    }
            center_flags = int(flags[int(round(y)), int(round(x))]) if inside else None
            finite = np.isfinite(image)
            variance = np.asarray(hdus["VARIANCE"].data)
            result = {
                "shape_yx": list(image.shape),
                "extensions": [h.name for h in hdus],
                "bunit": header.get("BUNIT"),
                "processing_version": str(hdus[0].header.get("VERSION", "")),
                "detector": int(header["DETECTOR"]),
                "obs_id": header.get("OBSID"),
                "requested_center_pixel_xy": [finite_float(x), finite_float(y)],
                "requested_center_inside_image": inside,
                "central_wavelength_um": center_wave,
                "central_bandwidth_um": center_width,
                "wavelength_min_um": finite_float(np.nanmin(wave)),
                "wavelength_max_um": finite_float(np.nanmax(wave)),
                "wavelength_model": "Approximate WCS-WAVE lookup; spectral SIP disabled",
                "finite_pixel_fraction": float(np.mean(finite)),
                "nonzero_flag_fraction": float(np.mean(flags != 0)),
                "flag_bit_counts": {
                    str(bit): int(np.count_nonzero(flags & (1 << bit)))
                    for bit in range(32)
                    if np.any(flags & (1 << bit))
                },
                "flag_definitions": flag_definitions,
                "center_flags": center_flags,
                "center_flag_names": [
                    definition["name"]
                    for bit, definition in flag_definitions.items()
                    if center_flags is not None and center_flags & (1 << int(bit))
                ],
                "positive_finite_variance_fraction": float(
                    np.mean(np.isfinite(variance) & (variance > 0))
                ),
                "science_percentiles_1_50_99": [
                    float(v) for v in np.percentile(image[finite], [1, 50, 99])
                ]
                if finite.any()
                else None,
                "psf_fwhm_arcsec": finite_float(header.get("PSF_FWHM")),
                "zodi_subtracted": False,
                "warnings": [
                    "Raw flags are preserved; nonzero does not always mean unusable.",
                    "A shared detector does not imply a shared wavelength.",
                    "This cutout is not a calibrated difference image or a measured spectrum.",
                ],
            }
            if not inside:
                result["warnings"].append(
                    "Observation only partially overlaps the requested field."
                )
            return result
    except ArchiveError:
        raise
    except Exception as exc:
        raise ArchiveError("Could not interpret the SPHEREx cutout and its WCS") from exc


def output_wcs(request: SearchRequest, pixels: int):
    wcs = WCS(naxis=2)
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    wcs.wcs.cunit = ["deg", "deg"]
    wcs.wcs.crval = [request.ra, request.dec]
    wcs.wcs.crpix = [(pixels + 1) / 2, (pixels + 1) / 2]
    wcs.wcs.cdelt = [-request.fov_arcmin / 60 / pixels, request.fov_arcmin / 60 / pixels]
    return wcs


def registered_image(path, request, pixels, reject_bits=0, subtract_zodi=False):
    with fits.open(path, memmap=False) as hdus:
        image = np.asarray(hdus["IMAGE"].data, dtype=np.float64)
        if subtract_zodi:
            image = image - hdus["ZODI"].data
        flags = np.asarray(hdus["FLAGS"].data, dtype=np.uint32)
        valid = np.isfinite(image) & ((flags & reject_bits) == 0)
        source_wcs = spatial_wcs(hdus["IMAGE"].header)
        target_wcs = output_wcs(request, pixels)
        yy, xx = np.indices((pixels, pixels), dtype=float)
        world = target_wcs.pixel_to_world(xx, yy)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            sx, sy = source_wcs.world_to_pixel(world)
        coordinates = np.array([sy, sx])
        coordinates[:, ~np.isfinite(sx) | ~np.isfinite(sy)] = -1
        support = map_coordinates(
            valid.astype(float), coordinates, order=1, mode="constant", cval=0, prefilter=False
        )
        result = map_coordinates(
            np.where(valid, image, 0),
            coordinates,
            order=1,
            mode="constant",
            cval=0,
            prefilter=False,
        )
        # Retain only fully supported bilinear samples, avoiding filled/masked edge artifacts.
        result[support < 1 - 1e-6] = np.nan
        return result


def asinh_unit_stretch(scaled):
    """Map a value already clipped to [-1, 1] through a signed asinh curve.

    Shared by the grayscale preview and the diverging difference renderer so
    their contrast behavior (and the stretch-strength constant) can't drift
    apart between the two call sites.
    """
    return np.sign(scaled) * np.arcsinh(10 * np.abs(scaled)) / np.arcsinh(10)


def encode_rgba_png(rgba_uint8):
    """PNG-encode an (H, W, 4) uint8 array. FITS lower-origin becomes PNG
    top-origin on the flip, so north stays up."""
    buffer = io.BytesIO()
    Image.fromarray(np.flipud(rgba_uint8)).save(buffer, format="PNG")
    return buffer.getvalue()


def preview_png(
    path, request, pixels=256, vmin=None, vmax=None, reject_bits=0, subtract_zodi=False
):
    image = registered_image(path, request, pixels, reject_bits, subtract_zodi)
    valid = np.isfinite(image)
    if not valid.any():
        raise ArchiveError("No valid pixels cover this preview after masking")
    if vmin is None:
        vmin, vmax = np.percentile(image[valid], [1, 99.5]).tolist()
        if vmax <= vmin:
            vmax = vmin + 1
    scaled = np.clip((np.nan_to_num(image, nan=vmin) - vmin) / (vmax - vmin), 0, 1)
    gray = np.round(asinh_unit_stretch(scaled) * 255).astype(np.uint8)
    rgba = np.stack([gray, gray, gray, valid.astype(np.uint8) * 255], axis=-1)
    return encode_rgba_png(rgba), {
        "X-Preview-Vmin": str(vmin),
        "X-Preview-Vmax": str(vmax),
        "X-Preview-Valid-Fraction": str(float(valid.mean())),
        "X-Preview-Scale": "asinh-10",
        "X-Preview-Orientation": "north-up-east-left",
        "X-Preview-Zodi-Subtracted": str(subtract_zodi).lower(),
    }


def difference_image(path_from, path_to, request, pixels, reject_bits=0, subtract_zodi=False):
    """Resample both cutouts onto one shared grid, then subtract (to minus from).

    Using the same ``request``/``pixels`` for both calls to ``registered_image``
    guarantees pixel-for-pixel alignment regardless of each cutout's own
    detector rotation. A pixel is valid only where both epochs are valid.
    """
    image_from = registered_image(path_from, request, pixels, reject_bits, subtract_zodi)
    image_to = registered_image(path_to, request, pixels, reject_bits, subtract_zodi)
    diff = image_to - image_from
    valid = np.isfinite(diff)
    return diff, valid


def difference_png(path_from, path_to, request, pixels=512, reject_bits=0, subtract_zodi=False):
    """Zero-centered, diverging quick-look PNG: red brightened, blue dimmed."""
    diff, valid = difference_image(path_from, path_to, request, pixels, reject_bits, subtract_zodi)
    if not valid.any():
        raise ArchiveError("No pixels are valid in both frames after masking")
    magnitude = float(np.percentile(np.abs(diff[valid]), 99.5))
    if magnitude <= 0:
        magnitude = 1.0
    scaled = np.clip(np.nan_to_num(diff, nan=0.0) / magnitude, -1, 1)
    stretched = asinh_unit_stretch(scaled)
    red = np.round(np.clip(stretched, 0, 1) * 255).astype(np.uint8)
    blue = np.round(np.clip(-stretched, 0, 1) * 255).astype(np.uint8)
    green = np.zeros_like(red)
    alpha = (valid.astype(np.uint8)) * 255
    rgba = np.stack([red, green, blue, alpha], axis=-1)
    return encode_rgba_png(rgba), {
        "X-Difference-Vmax": str(magnitude),
        "X-Difference-Scale": "asinh-10-diverging-red-positive-blue-negative",
        "X-Preview-Valid-Fraction": str(float(valid.mean())),
        "X-Preview-Orientation": "north-up-east-left",
    }


def full_sha256(payload):
    return hashlib.sha256(payload).hexdigest()
