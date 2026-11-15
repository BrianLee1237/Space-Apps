"""On-the-fly point-source spectral extraction across real SPHEREx exposures.

Samples temporally distributed exposures across all six detectors. Each point
reports its native pixel's wavelength and observation date. Wavelength coverage
depends on the archive and the linear variable filter placement.
"""

import re
import time

import astropy.units as u
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS

from .archive import ArchiveError
from .candidates import DEFAULT_CANDIDATE_REJECT_BITS
from .imaging import finite_float, output_wcs, spatial_wcs
from .models import SearchRequest
from .spectral import temporal_sample_groups

DETECTORS = (1, 2, 3, 4, 5, 6)


def resolve_pixel_sky_position(request, pixels, x_fraction, y_fraction):
    """Invert the xFraction/yFraction convention the PNG renderers use
    (north-up: the output array is flipped before encoding) back to a sky
    coordinate on that same output grid.
    """
    wcs = output_wcs(request, pixels)
    x = x_fraction * (pixels - 1)
    y = (1 - y_fraction) * (pixels - 1)
    coord = wcs.pixel_to_world(x, y)
    return float(coord.ra.deg), float(coord.dec.deg)


def point_sample(path, ra, dec):
    """Read the real flux, its 1-sigma uncertainty, quality flags, and the
    wavelength actually measured there, at one sky position in one native
    FITS cutout. Returns None if the position falls outside this exposure's
    own footprint or lands on a non-finite pixel.
    """
    with fits.open(path, memmap=False) as hdus:
        header = hdus["IMAGE"].header
        celestial = spatial_wcs(header)
        coord = SkyCoord(ra, dec, unit="deg", frame="icrs")
        x, y = (float(v) for v in celestial.world_to_pixel(coord))
        image = np.asarray(hdus["IMAGE"].data)
        if not (
            np.isfinite(x)
            and np.isfinite(y)
            and 0 <= x <= image.shape[1] - 1
            and 0 <= y <= image.shape[0] - 1
        ):
            return None
        xi, yi = int(round(x)), int(round(y))
        flux = finite_float(image[yi, xi])
        if flux is None:
            return None
        flags = np.asarray(hdus["FLAGS"].data, dtype=np.uint32)
        variance = np.asarray(hdus["VARIANCE"].data)
        var = finite_float(variance[yi, xi])
        uncertainty = float(np.sqrt(var)) if var is not None and var > 0 else None
        flag_header = hdus["FLAGS"].header
        center_flags = int(flags[yi, xi])
        if center_flags & DEFAULT_CANDIDATE_REJECT_BITS:
            return None
        flag_names = []
        for keyword in flag_header:
            match = re.fullmatch(r"MSKN(\d{4})", keyword)
            if match and center_flags & (1 << int(match[1])):
                flag_names.append(str(flag_header[keyword]))

        # Spectral WCS uses detector/filter geometry; SIP applies only to sky WCS.
        spectral_header = header.copy()
        for keyword in list(spectral_header):
            if re.fullmatch(r"(A|B|AP|BP)_(ORDER|\d+_\d+)", keyword):
                del spectral_header[keyword]
        spectral = WCS(spectral_header, fobj=hdus, key="W")
        spectral.sip = None
        wavelength, _bandwidth = spectral.pixel_to_world(x, y)
        wave_um = finite_float(wavelength.to_value(u.um))
        if wave_um is None:
            return None
        return {
            "wavelengthMicron": wave_um,
            "flux": flux,
            "uncertainty": uncertainty,
            "qualityFlags": flag_names,
            "bunit": header.get("BUNIT"),
        }


def build_fingerprint(sky, ra, dec, fov_arcmin, channels_per_detector=6):
    """Build a real spectral fingerprint at (ra, dec) from every detector's
    own available exposures, one representative real sample per temporal
    group. Returns (samples, warnings).

    ``channels_per_detector`` is retained for existing Python callers. It limits
    temporal samples per detector to six by default. These samples can repeat
    wavelengths and cannot guarantee complete coverage of the 102 channels.
    """
    query = SearchRequest(ra=ra, dec=dec, fov_arcmin=fov_arcmin, detectors=DETECTORS)
    manifest = sky.search(query)
    by_detector = {}
    for frame in manifest["frames"]:
        by_detector.setdefault(frame["detector"], []).append(frame)

    warnings = []
    if not manifest["complete"]:
        warnings.append(
            "The archive truncated this search; some epochs may be missing from this fingerprint."
        )
    missing = [d for d in DETECTORS if d not in by_detector]
    if missing:
        warnings.append(
            "No archived exposure was found at this position for detector(s) "
            + ", ".join(str(d) for d in missing)
            + "."
        )

    samples = []
    failed_downloads = 0
    for detector in DETECTORS:
        frames = by_detector.get(detector, [])
        if not frames:
            continue
        chunks = temporal_sample_groups(frames, groups=channels_per_detector)
        for group in chunks:
            found = None
            for frame in group:
                cached = sky.store.path("cutouts", frame["frame_id"], ".fits").exists()
                try:
                    path, _ = sky.frame(manifest["search_id"], frame["frame_id"])
                except ArchiveError:
                    # A fingerprint can fire dozens of real downloads across 6
                    # detectors; at that volume, one transient archive error is
                    # expected and shouldn't fail the whole fingerprint -- skip
                    # this exposure and try the next one for this channel.
                    failed_downloads += 1
                    continue
                sample = point_sample(path, ra, dec)
                if not cached:
                    # Pace real downloads rather than firing them back-to-back;
                    # IRSA's cutout service has rejected bursts of this size
                    # even though each individual download succeeds on its own.
                    time.sleep(0.2)
                if sample is not None:
                    found = sample
                    break
            if found is not None:
                found["observedAt"] = frame["observed_at_utc"]
                samples.append(found)

    samples.sort(key=lambda s: s["wavelengthMicron"])
    if not samples:
        warnings.append("No real exposure's own footprint covered this exact sky position.")
    if failed_downloads:
        warnings.append(
            f"{failed_downloads} exposure(s) could not be downloaded (a transient archive "
            "error) and were skipped rather than counted as missing coverage."
        )
    return samples, warnings
