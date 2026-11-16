"""Native-pixel aperture photometry with variance and local sky estimation."""

import json
from pathlib import Path

import astropy.units as u
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.stats import sigma_clip
from astropy.time import Time

from .candidates import DEFAULT_CANDIDATE_REJECT_BITS
from .imaging import spatial_wcs
from .spectrum import point_sample

CHANNELS = json.loads(Path(__file__).with_name("channels.json").read_text())
REJECT_BITS = DEFAULT_CANDIDATE_REJECT_BITS | sum(
    1 << bit for bit in (0, 6, 7, 10, 11, 14, 15, 17, 19, 29)
)
INFORMATIONAL_FLAGS = {"SOURCE", "FULLSAMPLE"}


def channel_for(wavelength, detector):
    candidates = [
        (index + 1, row)
        for index, row in enumerate(CHANNELS)
        if row["detector"] == detector and row["WL_MIN"] <= wavelength <= row["WL_MAX"]
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda item: abs(item[1]["WAVELENGTH"] - wavelength))[0]


def aperture_measurement(path, ra, dec, radius_arcsec=12, subtract_zodi=False):
    """Measure an uncorrected aperture flux in mJy on native calibrated pixels.

    Statistical errors include native variance and the estimated local sky.
    Spatial pixel areas are derived from local WCS offsets. Absolute calibration,
    PSF aperture correction, and correlated instrumental noise remain additional
    uncertainties. Known-source pixels are excluded from the background annulus.
    """
    sample = point_sample(path, ra, dec)
    if sample is None:
        return None
    with fits.open(path, memmap=False) as hdus:
        header = hdus["IMAGE"].header
        if str(header.get("BUNIT", "")).lower().replace(" ", "") != "mjy/sr":
            raise ValueError("Aperture photometry requires IMAGE units of MJy/sr")
        wcs = spatial_wcs(header)
        position = SkyCoord(ra, dec, unit="deg")
        x, y = (float(value) for value in wcs.world_to_pixel(position))
        center = wcs.pixel_to_world(x, y)
        east = wcs.pixel_to_world(x + 1, y)
        north = wcs.pixel_to_world(x, y + 1)
        ex, ey = center.spherical_offsets_to(east)
        nx, ny = center.spherical_offsets_to(north)
        solid_angle = abs(
            ex.to_value(u.rad) * ny.to_value(u.rad) - ey.to_value(u.rad) * nx.to_value(u.rad)
        )
        scale = np.sqrt(solid_angle) * u.rad.to(u.arcsec)
        if not np.isfinite(scale) or scale <= 0:
            return None
        radius = radius_arcsec / scale
        # Known-source masks can extend beyond the immediate aperture annulus.
        # A wider annulus leaves enough uncontaminated pixels for local sky.
        outer = 4 * radius
        image = np.asarray(hdus["IMAGE"].data, dtype=float)
        variance = np.asarray(hdus["VARIANCE"].data, dtype=float)
        flags = np.asarray(hdus["FLAGS"].data, dtype=np.uint32)
        if subtract_zodi:
            image = image - hdus["ZODI"].data
        x1, x2 = max(0, int(x - outer - 1)), min(image.shape[1], int(x + outer + 2))
        y1, y2 = max(0, int(y - outer - 1)), min(image.shape[0], int(y + outer + 2))
        yy, xx = np.mgrid[y1:y2, x1:x2]
        distances = np.hypot(xx - x, yy - y)
        weights = np.zeros_like(distances)
        for dx in (-0.4, -0.2, 0, 0.2, 0.4):
            for dy in (-0.4, -0.2, 0, 0.2, 0.4):
                weights += (np.hypot(xx + dx - x, yy + dy - y) <= radius) / 25
        values = image[y1:y2, x1:x2]
        errors = variance[y1:y2, x1:x2]
        bits = flags[y1:y2, x1:x2]
        valid = np.isfinite(values) & np.isfinite(errors) & (errors > 0)
        valid &= (bits & REJECT_BITS) == 0
        expected_area = np.pi * radius * radius
        coverage = float(np.sum(weights * valid) / expected_area)
        if coverage < 0.9:
            return None
        sky_mask = valid & (distances >= 1.5 * radius) & (distances <= outer)
        sky_mask &= (bits & (1 << 21)) == 0
        if np.count_nonzero(sky_mask) < 12:
            return None
        clipped = sigma_clip(values[sky_mask], sigma=3, maxiters=5, masked=True)
        retained = ~np.ma.getmaskarray(clipped)
        if np.count_nonzero(retained) < 12:
            return None
        sky_values = values[sky_mask][retained]
        sky_variances = errors[sky_mask][retained]
        background = float(np.median(sky_values))
        # Median standard error, with the measured sky scatter as a lower bound.
        scatter = 1.4826 * np.median(np.abs(sky_values - background))
        sky_error = np.pi / 2 * max(float(np.mean(sky_variances)), float(scatter**2))
        sky_error /= len(sky_values)
        retained_weights = weights * valid
        area = float(retained_weights.sum())
        flux = float(np.sum(retained_weights * np.where(valid, values - background, 0)))
        flux_variance = float(np.sum(retained_weights**2 * np.where(valid, errors, 0)))
        flux_variance += area * area * sky_error
        conversion = solid_angle * 1e9
        return {
            "flux": flux * conversion,
            "uncertainty": float(np.sqrt(flux_variance) * conversion),
            "background": background,
            "coverageFraction": min(1.0, coverage),
            "wavelengthMicron": sample["wavelengthMicron"],
            "channel": channel_for(sample["wavelengthMicron"], int(header["DETECTOR"])),
            "detector": int(header["DETECTOR"]),
            "qualityFlags": sample["qualityFlags"],
            "apertureRadiusArcsec": radius_arcsec,
            "pixelSolidAngleSr": float(solid_angle),
        }


def measure_lightcurve(records, ra, dec, radius_arcsec=12, progress=None, cancelled=None):
    samples, rejected = [], 0
    for index, record in enumerate(records):
        if cancelled:
            cancelled()
        measured = aperture_measurement(record["path"], ra, dec, radius_arcsec)
        if measured is None:
            rejected += 1
        else:
            samples.append(
                {**measured, "observationId": record["id"], "observedAt": record["observedAt"]}
            )
        if progress:
            progress(index + 1, len(records), "Measuring native aperture flux")
    summaries = []
    for channel in sorted({s["channel"] for s in samples if s["channel"] is not None}):
        selected = [s for s in samples if s["channel"] == channel]
        flux = np.array([s["flux"] for s in selected])
        uncertainty = np.array([s["uncertainty"] for s in selected])
        weight = 1 / uncertainty**2
        mean = float(np.sum(weight * flux) / np.sum(weight))
        chi2 = float(np.sum(((flux - mean) / uncertainty) ** 2))
        summaries.append(
            {
                "channel": channel,
                "count": len(selected),
                "meanFlux": mean,
                "reducedChiSquare": chi2 / (len(selected) - 1) if len(selected) > 1 else None,
            }
        )
    return {
        "samples": samples,
        "channels": summaries,
        "rejected": rejected,
        "fluxUnit": "mJy",
        "position": {"raDeg": ra, "decDeg": dec},
        "method": "Native fractional aperture, sigma-clipped annular sky, local WCS pixel area",
        "warnings": [
            "Aperture fluxes use calibrated IMAGE surface brightness. PSF aperture losses "
            "and absolute calibration systematics are additional uncertainties.",
            "Compare a single wavelength channel over time. Reduced chi-square describes "
            "scatter relative to statistical errors and requires independent validation.",
            f"Omitted {rejected} exposures with insufficient valid aperture "
            "or background coverage.",
        ],
    }


def wavelength_time_cells(samples, days=30):
    """Inverse-variance cells with scatter-inflated statistical uncertainty."""
    if not samples:
        return []
    first = min(Time(s["observedAt"]).mjd for s in samples)
    cells = {}
    for sample in samples:
        if sample["channel"] is None:
            continue
        epoch = int((Time(sample["observedAt"]).mjd - first) // days)
        cells.setdefault((epoch, sample["channel"]), []).append(sample)
    result = []
    for (epoch, channel), points in sorted(cells.items()):
        values = np.array([p["flux"] for p in points])
        weights = 1 / np.array([p["uncertainty"] for p in points]) ** 2
        mean = float(np.average(values, weights=weights))
        inflation = max(1, float(np.sum(weights * (values - mean) ** 2) / max(1, len(points) - 1)))
        result.append(
            {
                "epoch": epoch,
                "channel": channel,
                "flux": mean,
                "uncertainty": float(np.sqrt(inflation / weights.sum())),
                "count": len(points),
                "startMjd": first + epoch * days,
            }
        )
    return result
