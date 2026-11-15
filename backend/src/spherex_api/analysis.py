"""Conservative wavelength-matched pairs and observed (not simulated) centroid tracks.

This is quick-look science: a centroid association is NOT a verified moving object,
photometric measurement, or a physical proper-motion measurement.
"""

from __future__ import annotations

import math

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.time import Time
from scipy.ndimage import maximum_filter

from .candidates import DEFAULT_CANDIDATE_REJECT_BITS
from .imaging import output_wcs, registered_image


def wavelength_tolerance_um(wave_um: float) -> float:
    """A strict, documented quick-look display window, not a spectral calibration."""
    return max(0.012, 0.012 * wave_um)


def matched_pairs(entries, min_days: float = 1.0, limit: int = 12):
    """Rank combinations using actual FITS center wavelengths and observation metadata.

    entries: sequence of {id, observedAt, detector, wavelengthMicron, flags, release}.
    Missing wavelengths are excluded rather than silently assumed equivalent.
    """
    pairs = []
    for i, earlier in enumerate(entries):
        wa = earlier.get("wavelengthMicron")
        if wa is None or not math.isfinite(wa) or wa <= 0:
            continue
        for later in entries[i + 1 :]:
            wb = later.get("wavelengthMicron")
            if wb is None or not math.isfinite(wb) or wb <= 0:
                continue
            if earlier.get("detector") != later.get("detector"):
                continue
            days = (Time(later["observedAt"]).mjd - Time(earlier["observedAt"]).mjd)
            if days < min_days:
                continue
            delta = abs(wa - wb)
            mid = (wa + wb) / 2
            if delta > wavelength_tolerance_um(mid):
                continue
            flagged = bool(earlier.get("flags")) or bool(later.get("flags"))
            pairs.append(
                {
                    "fromId": earlier["id"],
                    "toId": later["id"],
                    "earlierAt": earlier["observedAt"],
                    "laterAt": later["observedAt"],
                    "elapsedDays": round(float(days), 2),
                    "detector": earlier["detector"],
                    "wavelengthMicron": round(float(mid), 5),
                    "wavelengthDifferencePercent": round(100 * delta / mid, 3),
                    "hasQualityFlags": flagged,
                }
            )
    # Prefer unflagged pairs, a longer baseline, then a tighter wavelength match.
    pairs.sort(
        key=lambda p: (
            p["hasQualityFlags"],
            -p["elapsedDays"],
            p["wavelengthDifferencePercent"],
        )
    )
    return pairs[:limit]


def _local_centroid(image, x, y, radius, min_snr=5.0):
    """Find nearest significant positive peak and centroid it on a real registered image.

    Background and noise are estimated robustly in a surrounding patch. The
    amplitude is only a detection statistic; it is not calibrated photometry.
    """
    height, width = image.shape
    x1, x2 = max(0, int(math.floor(x - radius))), min(width, int(math.ceil(x + radius)) + 1)
    y1, y2 = max(0, int(math.floor(y - radius))), min(height, int(math.ceil(y + radius)) + 1)
    if x2 - x1 < 5 or y2 - y1 < 5:
        return None
    # Estimate sky/noise in a much wider window than the peak-search window.
    # A small peak window lies entirely within a real source's PSF and its
    # median is NOT the sky background; that would reject bright broad stars.
    bg_radius = max(48, min(180, 3.0 * radius))
    bx1, bx2 = max(0, int(math.floor(x-bg_radius))), min(width, int(math.ceil(x+bg_radius))+1)
    by1, by2 = max(0, int(math.floor(y-bg_radius))), min(height, int(math.ceil(y+bg_radius))+1)
    bg_patch = image[by1:by2, bx1:bx2]
    bg_valid = np.isfinite(bg_patch)
    if np.count_nonzero(bg_valid) < 25:
        return None
    bg_values = bg_patch[bg_valid]
    background = float(np.median(bg_values))
    sigma = float(1.4826 * np.median(np.abs(bg_values - background)))
    if sigma <= 1e-10 or not np.isfinite(sigma):
        sigma = float(np.std(bg_values))
    if sigma <= 1e-10 or not np.isfinite(sigma):
        return None
    patch = image[y1:y2, x1:x2]
    valid = np.isfinite(patch)
    if np.count_nonzero(valid) < max(9, int(0.5 * patch.size)):
        return None
    score = np.where(valid, patch - background, -np.inf)
    peak_mask = (score == maximum_filter(score, size=3, mode="nearest")) & (score >= min_snr * sigma)
    yy, xx = np.where(peak_mask)
    if len(xx) == 0:
        return None
    dist = (xx + x1 - x) ** 2 + (yy + y1 - y) ** 2
    # Prefer the strongest significant peak, mildly penalizing displacement.
    # Picking the nearest local maximum confuses noise ripples in a broad PSF
    # with a genuine source center.
    candidate_signal = score[yy, xx] / (1 + 0.25 * dist / max(16.0, radius * radius))
    j = int(np.argmax(candidate_signal))
    px, py = int(xx[j]) + x1, int(yy[j]) + y1
    # Centroid a small local PSF footprint (avoid including other sources).
    cx1, cx2 = max(0, px - 2), min(width, px + 3)
    cy1, cy2 = max(0, py - 2), min(height, py + 3)
    region = image[cy1:cy2, cx1:cx2]
    weights = np.where(np.isfinite(region), np.maximum(region - background, 0), 0)
    total = float(weights.sum())
    if total <= 0:
        return None
    ry, rx = np.indices(region.shape)
    return {
        "x": float(cx1 + (rx * weights).sum() / total),
        "y": float(cy1 + (ry * weights).sum() / total),
        "peakSnr": round(float(score[yy[j], xx[j]] / sigma), 2),
    }


def track_source(frames, reference_id, x_fraction, y_fraction, max_shift_arcsec=45, pixels=512):
    """Measure provisional centroids in multiple real, registered FITS exposures.

    ``frames`` is a chronological list of records with id, path, request,
    metadata. Only same-detector, wavelength-matched frames are accepted;
    invalid or absent detections produce no fabricated coordinates.
    """
    if not 0 <= x_fraction <= 1 or not 0 <= y_fraction <= 1:
        raise ValueError("Selection must lie inside the displayed image")
    if not 5 <= max_shift_arcsec <= 120:
        raise ValueError("Maximum displacement must be 5-120 arcsec")
    reference = next((f for f in frames if f["id"] == reference_id), None)
    if reference is None:
        raise ValueError("Reference observation must be one of the requested frames")
    request = reference["request"]
    wave_ref = reference["metadata"].get("central_wavelength_um")
    detector = reference["metadata"].get("detector")
    if wave_ref is None or not math.isfinite(wave_ref) or wave_ref <= 0:
        return {"measurements": [], "warnings": ["Reference wavelength is unknown; cannot match epochs safely."], "summary": None}
    pixel_scale = request.fov_arcmin * 60 / pixels
    max_radius_px = min(100, max(4.0, max_shift_arcsec / pixel_scale))
    wcs = output_wcs(request, pixels)
    x0 = x_fraction * (pixels - 1)
    y0 = (1 - y_fraction) * (pixels - 1)
    warnings = [
        "Quick-look centroid associations are unverified. Nearby stars, PSF changes, "
        "spectral response and artifacts can imitate motion.",
        "Centroid positions have no validated astrometric error bars; reported shift "
        "is not a confirmed physical proper motion.",
    ]
    # Find an anchor source within three pixels of the user's click.
    try:
        image_ref = registered_image(reference["path"], request, pixels, reject_bits=DEFAULT_CANDIDATE_REJECT_BITS)
    except Exception:
        return {"measurements": [], "warnings": [*warnings, "Reference image could not be registered."], "summary": None}
    anchor = _local_centroid(image_ref, x0, y0, 4)
    if anchor is None:
        return {"measurements": [], "warnings": [*warnings, "No significant source near the selected position."], "summary": None}
    output = []
    excluded = 0
    missed = 0
    for entry in sorted(frames, key=lambda f: f["observedAt"]):
        meta = entry["metadata"]
        wave = meta.get("central_wavelength_um")
        other = entry["request"]
        same_field = (
            abs(other.ra - request.ra) < 1e-7
            and abs(other.dec - request.dec) < 1e-7
            and abs(other.fov_arcmin - request.fov_arcmin) < 1e-7
        )
        if (not same_field or meta.get("detector") != detector or wave is None
                or not math.isfinite(wave) or abs(wave - wave_ref) > wavelength_tolerance_um(wave_ref)):
            excluded += 1
            continue
        if entry["id"] == reference_id:
            measured = anchor
        else:
            try:
                registered = registered_image(entry["path"], request, pixels, reject_bits=DEFAULT_CANDIDATE_REJECT_BITS)
                measured = _local_centroid(registered, anchor["x"], anchor["y"], max_radius_px)
            except Exception:
                measured = None
        if measured is None:
            missed += 1
            continue
        world = wcs.pixel_to_world(measured["x"], measured["y"])
        position = SkyCoord(world.ra, world.dec)
        output.append({
            "observationId": entry["id"],
            "observedAt": entry["observedAt"],
            "xFraction": round(measured["x"] / (pixels - 1), 6),
            "yFraction": round(1 - measured["y"] / (pixels - 1), 6),
            "raDeg": round(float(position.ra.deg), 9),
            "decDeg": round(float(position.dec.deg), 9),
            "peakSnr": measured["peakSnr"],
            "wavelengthMicron": round(float(wave), 5),
        })
    if excluded:
        warnings.append(f"Excluded {excluded} incompatible detector, wavelength or field exposures.")
    if missed:
        warnings.append(f"Could not find a significant nearby peak in {missed} compatible exposure(s).")
    summary = None
    if len(output) >= 2:
        earlier, later = output[0], output[-1]
        t = (Time(later["observedAt"]).mjd - Time(earlier["observedAt"]).mjd)
        a = SkyCoord(earlier["raDeg"], earlier["decDeg"], unit="deg")
        b = SkyCoord(later["raDeg"], later["decDeg"], unit="deg")
        shift_arcsec = float(a.separation(b).arcsec)
        summary = {
            "baselineDays": round(float(t), 2),
            "apparentShiftArcsec": round(shift_arcsec, 3),
            "apparentRateArcsecPerYear": round(shift_arcsec / (t / 365.25), 3) if t > 0 else None,
            "observationsMeasured": len(output),
        }
        if t < 30:
            warnings.append("Baseline shorter than 30 days; movement is especially uncertain.")
    return {"measurements": output, "warnings": warnings, "summary": summary}
