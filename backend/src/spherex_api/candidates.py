"""Blob-based moving/changing-source candidate detection from a difference image.

This flags statistically significant residual blobs in a to-minus-from
difference image (see imaging.difference_image), pairs a brightened blob with
a nearby dimmed blob into a single "moving source" candidate (the classic
Pluto-discovery / Backyard Worlds blink-comparison signature), and reports
leftover unpaired blobs as "brightness change" candidates (e.g. a variable
star). Candidates are unverified: no PSF fitting, no cross-matching against a
source catalog, no vetting against cosmic rays or detector artifacts beyond
the rejected quality-flag bits.
"""

import math

import numpy as np
from astropy.time import Time
from scipy import ndimage

from .imaging import difference_image, output_wcs

# Flags most likely to fake a "moving source" dipole rather than reflect real
# sky motion: detector artifacts, not an astrophysical source or outlier pixel.
DEFAULT_CANDIDATE_REJECT_BITS = sum(
    1 << bit for bit in (1, 2, 9, 20, 22, 23, 24, 25, 26, 27, 28)
)


def _blobs(mask, score, median, raw):
    labels, count = ndimage.label(mask)
    found = []
    for index in range(1, count + 1):
        ys, xs = np.where(labels == index)
        weight = np.abs(score[ys, xs] - median)
        total_weight = float(weight.sum())
        if total_weight <= 0:
            continue
        found.append(
            {
                "x": float(np.average(xs, weights=weight)),
                "y": float(np.average(ys, weights=weight)),
                "peak": float(np.max(weight)),
                "raw_peak": float(np.max(np.abs(raw[ys, xs]))),
                "npix": int(ys.size),
            }
        )
    return found


def detect_candidates(
    path_earlier,
    path_later,
    request,
    earlier_iso,
    later_iso,
    pixels=512,
    reject_bits=DEFAULT_CANDIDATE_REJECT_BITS,
    sigma_threshold=10.0,
    min_blob_pixels=25,
    max_pair_arcsec=90.0,
    edge_erosion_px=6,
    background_arcsec=60.0,
    max_candidates=8,
):
    """Detect candidates between two epochs on ``request``'s output grid.

    Returns (candidates, warnings). ``candidates`` entries match the frontend's
    ``Candidate`` shape. Coordinates come directly from ``output_wcs`` pixel
    positions, consistent with how difference_png renders the same grid.
    """
    diff, valid = difference_image(path_earlier, path_later, request, pixels, reject_bits)
    warnings = [
        "Candidates are unverified: no PSF fitting, catalog cross-match, or "
        "cosmic-ray vetting beyond the rejected quality-flag bits.",
        "Brightness-change-only candidates do not confirm variability; a single "
        "epoch pair cannot distinguish a real change from a processing artifact.",
    ]
    if not valid.any():
        return [], [*warnings, "No valid overlapping pixels between the two frames."]

    # The two frames' native detector rotations rarely match, so their
    # resampled valid/invalid boundaries fall at different pixels. Right at
    # that ragged edge, partial-coverage interpolation can fake a sharp
    # gradient that looks like a real dipole. Erode inward so detection only
    # runs where both frames have solid, non-edge coverage.
    safe = ndimage.binary_erosion(valid, iterations=edge_erosion_px, border_value=0)
    if not safe.any():
        return [], [*warnings, "No interior pixels are valid in both frames after masking."]

    # Two independent exposures rarely share the same large-scale background
    # (zodiacal light, flat-fielding residuals): subtract a local median
    # "background" of the difference itself so a smooth, field-wide offset
    # doesn't masquerade as thousands of individually-significant pixels.
    # The kernel is much wider than the PSF, so a real compact source barely
    # biases its own local background estimate.
    pixel_scale_arcsec = request.fov_arcmin * 60 / pixels
    kernel_px = max(15, int(round(background_arcsec / pixel_scale_arcsec)))
    fill_value = float(np.median(diff[safe]))
    filled = np.where(valid, diff, fill_value)
    background = ndimage.median_filter(filled, size=kernel_px, mode="nearest")
    residual = diff - background

    values = residual[safe]
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    sigma = mad * 1.4826 if mad > 0 else (float(np.std(values)) or 1.0)
    threshold = sigma_threshold * sigma

    # The output grid oversamples the native ~6" detector pixels by roughly
    # 4x per axis (see output_wcs), so bilinear resampling correlates noise
    # across several adjacent output pixels: one noisy native pixel can look
    # like a many-output-pixel blob. min_blob_pixels defaults to roughly a
    # PSF-sized footprint (psf_fwhm_arcsec) at this pixel scale, so it takes
    # a source-sized blob, not a smeared single native pixel, to pass.
    positive = _blobs(safe & (residual - median > threshold), residual, median, diff)
    negative = _blobs(safe & (median - residual > threshold), residual, median, diff)
    positive = [b for b in positive if b["npix"] >= min_blob_pixels]
    negative = [b for b in negative if b["npix"] >= min_blob_pixels]

    # A handful of pixels near a bright/saturated star can carry a raw
    # difference far outside the normal science range (detector overflow or
    # bleed, not linear flux); such a spike is not a credible point-source
    # measurement, so drop it rather than report an absurd "discovery".
    implausible_raw = max(50.0, float(np.percentile(np.abs(diff[safe]), 99.9)) * 20)
    positive = [b for b in positive if b["raw_peak"] <= implausible_raw]
    negative = [b for b in negative if b["raw_peak"] <= implausible_raw]

    wcs = output_wcs(request, pixels)
    max_pair_px = max_pair_arcsec / pixel_scale_arcsec
    elapsed_days = _days_between(earlier_iso, later_iso)
    method = (
        f"{sigma_threshold:g}-sigma blob detection on a to-minus-from difference image, "
        "after subtracting a local median background"
    )

    def to_sky_fraction(x, y):
        coord = wcs.pixel_to_world(x, y)
        return float(coord.ra.deg), float(coord.dec.deg), x / (pixels - 1), 1 - y / (pixels - 1)

    candidates = []
    used_negative = set()
    for blob in sorted(positive, key=lambda b: -b["peak"]):
        best_index, best_distance = None, None
        for index, other in enumerate(negative):
            if index in used_negative:
                continue
            distance = math.hypot(blob["x"] - other["x"], blob["y"] - other["y"])
            if distance <= max_pair_px and (best_distance is None or distance < best_distance):
                best_index, best_distance = index, distance
        if best_index is None:
            ra, dec, xf, yf = to_sky_fraction(blob["x"], blob["y"])
            candidates.append(
                _candidate(
                    f"bright-{round(blob['x'])}-{round(blob['y'])}",
                    ra,
                    dec,
                    xf,
                    yf,
                    "brightness-change",
                    None,
                    blob["peak"],
                    f"Brightened by {blob['peak']:.3g} (native surface-brightness units) "
                    f"with no matching dimmed region nearby; could be a variable source or "
                    f"an unmatched artifact.",
                    method,
                )
            )
            continue
        used_negative.add(best_index)
        other = negative[best_index]
        ra, dec, xf, yf = to_sky_fraction(blob["x"], blob["y"])
        displacement_arcsec = best_distance * pixel_scale_arcsec
        rate_note = ""
        if elapsed_days and elapsed_days > 0:
            rate_arcsec_per_year = displacement_arcsec / (elapsed_days / 365.25)
            rate_note = f"; implies {rate_arcsec_per_year:.2f} arcsec/yr if linear"
        candidates.append(
            _candidate(
                f"mover-{round(blob['x'])}-{round(blob['y'])}",
                ra,
                dec,
                xf,
                yf,
                "moving-source",
                displacement_arcsec,
                None,
                f"Brightened blob paired with a dimmed blob {displacement_arcsec:.2f} arcsec "
                f"away over {elapsed_days:.1f} day(s){rate_note}.",
                method,
            )
        )
    for index, other in enumerate(negative):
        if index in used_negative:
            continue
        ra, dec, xf, yf = to_sky_fraction(other["x"], other["y"])
        candidates.append(
            _candidate(
                f"dim-{round(other['x'])}-{round(other['y'])}",
                ra,
                dec,
                xf,
                yf,
                "brightness-change",
                None,
                -other["peak"],
                f"Dimmed by {other['peak']:.3g} (native surface-brightness units) with no "
                f"matching brightened region nearby; could be a variable source or an "
                f"unmatched artifact.",
                method,
            )
        )
    candidates.sort(key=lambda c: -abs(c["brightnessChange"] or c["displacementArcsec"] or 0))
    if len(candidates) > max_candidates:
        warnings.append(
            f"Showing the {max_candidates} most significant of {len(candidates)} detections "
            "above threshold; the rest are omitted, not ruled out."
        )
        candidates = candidates[:max_candidates]
    return candidates, warnings


def _candidate(id_, ra, dec, xf, yf, classification, displacement, brightness, notes, method):
    return {
        "id": id_,
        "raDeg": ra,
        "decDeg": dec,
        "xFraction": xf,
        "yFraction": yf,
        "classification": classification,
        "displacementArcsec": displacement,
        "brightnessChange": brightness,
        "method": method,
        "notes": notes,
    }


def _days_between(earlier_iso, later_iso):
    return (Time(later_iso) - Time(earlier_iso)).jd
