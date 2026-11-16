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
from .photometry import channel_for
from .processing import reference_registration
from .spectrum import point_sample


def wavelength_tolerance_um(wave_um: float) -> float:
    """A strict, documented quick-look display window, not a spectral calibration."""
    return max(0.012, 0.012 * wave_um)


def matched_pairs(entries, min_days: float = 1.0, limit: int = 12):
    """Rank combinations using actual FITS center wavelengths and observation metadata.

    entries: sequence of {id, observedAt, detector, wavelengthMicron, flags, release}.
    Missing wavelengths are excluded rather than silently assumed equivalent.
    """
    entries = sorted(entries, key=lambda row: row["observedAt"])
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
            qa, qb = earlier.get("request"), later.get("request")
            if (
                qa is not None
                and qb is not None
                and any(
                    abs(getattr(qa, key) - getattr(qb, key)) > 1e-7
                    for key in ("ra", "dec", "fov_arcmin")
                )
            ):
                continue
            days = Time(later["observedAt"]).mjd - Time(earlier["observedAt"]).mjd
            if days < min_days:
                continue
            ca = channel_for(wa, earlier["detector"])
            cb = channel_for(wb, later["detector"])
            if ca is None or ca != cb:
                continue
            delta = abs(wa - wb)
            mid = (wa + wb) / 2
            if delta > wavelength_tolerance_um(mid):
                continue
            flagged = any(
                flag not in {"SOURCE", "FULLSAMPLE"}
                for row in (earlier, later)
                for flag in row.get("flags", [])
            )
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
    bx1, bx2 = max(0, int(math.floor(x - bg_radius))), min(width, int(math.ceil(x + bg_radius)) + 1)
    by1, by2 = (
        max(0, int(math.floor(y - bg_radius))),
        min(height, int(math.ceil(y + bg_radius)) + 1),
    )
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
    peak_mask = (score == maximum_filter(score, size=3, mode="nearest")) & (
        score >= min_snr * sigma
    )
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


def track_source(
    frames,
    reference_id,
    x_fraction,
    y_fraction,
    max_shift_arcsec=45,
    pixels=512,
    progress=None,
    cancelled=None,
):
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
    source_position = output_wcs(request, pixels).pixel_to_world(
        x_fraction * (pixels - 1), (1 - y_fraction) * (pixels - 1)
    )
    reference_sample = point_sample(
        reference["path"], source_position.ra.deg, source_position.dec.deg
    )
    wave_ref = reference_sample["wavelengthMicron"] if reference_sample else None
    detector = reference["metadata"].get("detector")
    if wave_ref is None or not math.isfinite(wave_ref) or wave_ref <= 0:
        return {
            "measurements": [],
            "warnings": ["Reference wavelength is unknown; cannot match epochs safely."],
            "summary": None,
        }
    pixel_scale = request.fov_arcmin * 60 / pixels
    max_radius_px = min(100, max(4.0, max_shift_arcsec / pixel_scale))
    wcs = output_wcs(request, pixels)
    x0 = x_fraction * (pixels - 1)
    y0 = (1 - y_fraction) * (pixels - 1)
    warnings = [
        "Quick-look centroid associations are unverified. Nearby stars, PSF changes, "
        "spectral response and artifacts can imitate motion.",
        "Position errors combine PSF/SNR statistical estimates with an assumed 0.5-arcsec "
        "astrometric floor. This floor requires validation against reference stars.",
    ]
    # Find an anchor source within three pixels of the user's click.
    try:
        image_ref = registered_image(
            reference["path"], request, pixels, reject_bits=DEFAULT_CANDIDATE_REJECT_BITS
        )
    except Exception:
        return {
            "measurements": [],
            "warnings": [*warnings, "Reference image could not be registered."],
            "summary": None,
        }
    anchor = _local_centroid(image_ref, x0, y0, 4)
    if anchor is None:
        return {
            "measurements": [],
            "warnings": [*warnings, "No significant source near the selected position."],
            "summary": None,
        }
    output = []
    excluded = 0
    missed = 0
    for index, entry in enumerate(sorted(frames, key=lambda f: f["observedAt"])):
        if cancelled:
            cancelled()
        if progress:
            progress(index + 1, len(frames), "Measuring source and reference-star positions")
        registration = {"dx": 0.0, "dy": 0.0, "stars": 0, "scatterPixels": None}
        meta = entry["metadata"]
        sample = point_sample(entry["path"], source_position.ra.deg, source_position.dec.deg)
        wave = sample["wavelengthMicron"] if sample else None
        other = entry["request"]
        same_field = (
            abs(other.ra - request.ra) < 1e-7
            and abs(other.dec - request.dec) < 1e-7
            and abs(other.fov_arcmin - request.fov_arcmin) < 1e-7
        )
        if (
            not same_field
            or meta.get("detector") != detector
            or wave is None
            or not math.isfinite(wave)
            or abs(wave - wave_ref) > wavelength_tolerance_um(wave_ref)
        ):
            excluded += 1
            continue
        if entry["id"] == reference_id:
            measured = anchor
        else:
            try:
                registered = registered_image(
                    entry["path"], request, pixels, reject_bits=DEFAULT_CANDIDATE_REJECT_BITS
                )
                registration = reference_registration(
                    image_ref, registered, (anchor["x"], anchor["y"])
                )
                measured = _local_centroid(
                    registered,
                    anchor["x"] + registration["dx"],
                    anchor["y"] + registration["dy"],
                    max_radius_px,
                )
                if measured:
                    measured["x"] -= registration["dx"]
                    measured["y"] -= registration["dy"]
            except Exception:
                measured = None
        if measured is None:
            missed += 1
            continue
        world = wcs.pixel_to_world(measured["x"], measured["y"])
        position = SkyCoord(world.ra, world.dec)
        output.append(
            {
                "observationId": entry["id"],
                "observedAt": entry["observedAt"],
                "xFraction": round(measured["x"] / (pixels - 1), 6),
                "yFraction": round(1 - measured["y"] / (pixels - 1), 6),
                "raDeg": round(float(position.ra.deg), 9),
                "decDeg": round(float(position.dec.deg), 9),
                "peakSnr": measured["peakSnr"],
                "referenceStars": registration["stars"],
                "registrationScatterArcsec": (registration["scatterPixels"] * pixel_scale)
                if registration["scatterPixels"] is not None
                else None,
                "uncertaintyArcsec": round(
                    float(
                        np.hypot(
                            (meta.get("psf_fwhm_arcsec") or 2.355 * pixel_scale)
                            / (2.355 * max(measured["peakSnr"], 1)),
                            0.5,
                        )
                    ),
                    4,
                ),
                "wavelengthMicron": round(float(wave), 5),
            }
        )
    if excluded:
        warnings.append(
            f"Excluded {excluded} incompatible detector, wavelength or field exposures."
        )
    if missed:
        warnings.append(
            f"Could not find a significant nearby peak in {missed} compatible exposure(s)."
        )
    summary = None
    if len(output) >= 2:
        earlier, later = output[0], output[-1]
        t = Time(later["observedAt"]).mjd - Time(earlier["observedAt"]).mjd
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
    if any(row["observationId"] != reference_id and row["referenceStars"] < 3 for row in output):
        warnings.append(
            "Some epochs lack three isolated reference stars; their WCS alignment is retained."
        )
    model = fit_motion(output)
    if model and model.get("reducedChiSquare") is not None and model["reducedChiSquare"] > 3:
        warnings.append(
            "The linear track has excess scatter. Check blends, parallax, and source association."
        )
    return {"measurements": output, "warnings": warnings, "summary": summary, "fit": model}


def fit_motion(measurements):
    """Weighted tangent-plane linear motion with an explicitly assumed error model."""
    if len(measurements) < 2:
        return None
    times = np.array([Time(row["observedAt"]).mjd for row in measurements])
    if np.ptp(times) <= 0:
        return None
    origin = measurements[0]
    center = SkyCoord(origin["raDeg"], origin["decDeg"], unit="deg")
    coordinates = SkyCoord(
        [row["raDeg"] for row in measurements], [row["decDeg"] for row in measurements], unit="deg"
    )
    east, north = center.spherical_offsets_to(coordinates)
    values = np.stack([east.arcsec, north.arcsec], axis=1)
    errors = np.array([row.get("uncertaintyArcsec", 0.5) for row in measurements])
    weight = 1 / errors**2
    epoch = float(np.average(times, weights=weight))
    design = np.stack([np.ones(len(times)), (times - epoch) / 365.25], axis=1)
    normal = design.T @ (weight[:, None] * design)
    covariance = np.linalg.inv(normal)
    coefficients = covariance @ design.T @ (weight[:, None] * values)
    residuals = values - design @ coefficients
    dof = 2 * len(times) - 4
    reduced = float(np.sum((residuals / errors[:, None]) ** 2) / dof) if dof > 0 else None
    inflation = max(1, reduced or 1)
    rate_error = float(np.sqrt(covariance[1, 1] * inflation))
    return {
        "eastArcsecPerYear": float(coefficients[1, 0]),
        "northArcsecPerYear": float(coefficients[1, 1]),
        "rateUncertaintyArcsecPerYear": rate_error,
        "referenceMjd": epoch,
        "reducedChiSquare": reduced,
        "degreesOfFreedom": dof,
        "assumedAstrometricFloorArcsec": 0.5,
        "model": "Weighted linear tangent-plane motion; parallax and acceleration omitted",
    }


def discover_changes(records, progress=None, cancelled=None):
    """Find disjoint matched pairs and associate repeat residuals on a PSF scale."""
    from .candidates import detect_candidates
    from .storage import digest

    pairs = matched_pairs(records, min_days=1, limit=1000)
    by_id = {row["id"]: row for row in records}
    selected, used = [], set()
    for pair in pairs:
        if pair["fromId"] in used or pair["toId"] in used:
            continue
        selected.append(pair)
        used.update((pair["fromId"], pair["toId"]))
        if len(selected) == 3:
            break
    found, warnings = [], []
    for index, pair in enumerate(selected):
        if cancelled:
            cancelled()
        a, b = by_id[pair["fromId"]], by_id[pair["toId"]]
        items, notes = detect_candidates(
            a["path"], b["path"], a["request"], a["observedAt"], b["observedAt"]
        )
        warnings.extend(notes)
        psf = max(
            a["metadata"].get("psf_fwhm_arcsec") or 6.2, b["metadata"].get("psf_fwhm_arcsec") or 6.2
        )
        for item in items:
            coordinate = SkyCoord(item["raDeg"], item["decDeg"], unit="deg")
            same = next(
                (
                    previous
                    for previous in found
                    if coordinate.separation(
                        SkyCoord(previous["raDeg"], previous["decDeg"], unit="deg")
                    ).arcsec
                    <= 1.5 * psf
                ),
                None,
            )
            evidence = {
                **pair,
                "associationRadiusArcsec": 1.5 * psf,
                "detectionThresholdSigma": 10,
                "method": item["method"],
            }
            if same:
                same["evidence"].append(evidence)
            else:
                item["evidence"] = [evidence]
                found.append(item)
        if progress:
            progress(index + 1, len(selected), "Comparing wavelength-compatible epochs")
    found.sort(key=lambda row: -len(row["evidence"]))
    for index, item in enumerate(found[:12]):
        item["id"] = digest(f"{item['raDeg']:.6f}:{item['decDeg']:.6f}:" + canonical_evidence(item))
        item["label"] = f"Change {index + 1}"
        item["supportingPairs"] = len(item["evidence"])
        item["caption"] += (
            f" Supported by {len(item['evidence'])} disjoint wavelength-matched epoch pair(s)."
        )
    if not selected:
        warnings.append("No wavelength-compatible independent epoch pairs were available.")
    return {
        "candidates": found[:12],
        "method": "Disjoint wavelength-matched residual comparisons",
        "notes": f"Compared {len(selected)} independent pairs from {len(records)} exposures.",
        "warnings": list(dict.fromkeys(warnings)),
    }


def canonical_evidence(item):
    return "|".join(sorted(row["fromId"] + row["toId"] for row in item["evidence"]))
