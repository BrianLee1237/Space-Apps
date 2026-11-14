"""Measured native-pixel surface-brightness samples for interactive inspection."""

import re
from concurrent.futures import ThreadPoolExecutor

import astropy.units as u
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS

from .candidates import DEFAULT_CANDIDATE_REJECT_BITS
from .imaging import output_wcs, spatial_wcs
from .models import SearchRequest


def extract_spectrum(sky, search_id, x, y, ra=None, dec=None):
    manifest = sky.manifest(search_id)
    request = SearchRequest.model_validate(manifest["query"])
    coord = (
        SkyCoord(ra, dec, unit="deg")
        if ra is not None
        else output_wcs(request, 512).pixel_to_world(x * 511, (1 - y) * 511)
    )
    frames = manifest["frames"]
    indices = np.unique(np.linspace(0, len(frames) - 1, min(16, len(frames)), dtype=int))

    def measure(index):
        frame = frames[index]
        try:
            path, _ = sky.frame(search_id, frame["frame_id"])
            with fits.open(path, memmap=False) as hdus:
                px, py = map(float, spatial_wcs(hdus["IMAGE"].header).world_to_pixel(coord))
                ix, iy = int(round(px)), int(round(py))
                image = hdus["IMAGE"].data
                if not (1 <= ix < image.shape[1] - 1 and 1 <= iy < image.shape[0] - 1):
                    return None
                patch = np.s_[iy - 1 : iy + 2, ix - 1 : ix + 2]
                values = image[patch] - hdus["ZODI"].data[patch]
                variance = hdus["VARIANCE"].data[patch]
                flags = np.asarray(hdus["FLAGS"].data[patch], dtype=np.uint32)
                valid = (
                    np.isfinite(values)
                    & np.isfinite(variance)
                    & (variance > 0)
                    & ((flags & DEFAULT_CANDIDATE_REJECT_BITS) == 0)
                )
                if not valid.any():
                    return None
                header = hdus["IMAGE"].header.copy()
                for keyword in list(header):
                    if re.fullmatch(r"(A|B|AP|BP)_(ORDER|\d+_\d+)", keyword):
                        del header[keyword]
                spectral = WCS(header, fobj=hdus, key="W")
                spectral.sip = None
                wavelength, _ = spectral.pixel_to_world(px, py)
                return {
                    "wavelengthMicron": float(wavelength.to_value(u.um)),
                    "flux": float(values[valid].mean()),
                    "uncertainty": float(np.sqrt(variance[valid].sum()) / valid.sum()),
                    "observedAt": frame["observed_at_utc"],
                    "qualityFlags": ["PARTIAL_APERTURE"] if valid.sum() < 9 else [],
                }
        except (OSError, ValueError, RuntimeError):
            return None

    with ThreadPoolExecutor(max_workers=3) as pool:
        samples = [sample for sample in pool.map(measure, indices) if sample is not None]
    return {
        "samples": sorted(samples, key=lambda sample: sample["wavelengthMicron"]),
        "fluxUnit": "MJy/sr",
        "extractionMethod": "Native 3 × 3 pixel mean after zodiacal-model subtraction",
        "sourceLabel": f"ICRS {coord.ra.deg:.5f}°, {coord.dec.deg:.5f}°",
        "warnings": [
            f"{len(samples)} usable samples from {len(indices)} sampled detector exposures.",
            "Surface brightness across dates. Wavelength and time both vary.",
            "Aperture, PSF, and local-background corrections require further analysis.",
        ],
    }
