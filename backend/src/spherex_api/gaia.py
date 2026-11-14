"""Gaia DR3 catalog overlay via ESA's Gaia Archive TAP+ synchronous query service."""

import math

import httpx
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.time import Time

from .archive import ArchiveError
from .imaging import output_wcs

GAIA_TAP_URL = "https://gea.esac.esa.int/tap-server/tap/sync"
GAIA_COLUMNS = (
    "source_id",
    "ra",
    "dec",
    "phot_g_mean_mag",
    "pmra",
    "pmdec",
    "parallax",
    "ref_epoch",
)


class GaiaClient:
    """A thin client for ESA's Gaia Archive TAP+ ``sync`` ADQL endpoint."""

    def __init__(self, settings, transport=None):
        self.client = httpx.Client(
            timeout=httpx.Timeout(settings.timeout_seconds, connect=20),
            transport=transport,
            headers={"User-Agent": "SPHERExSkyAPI/0.1 (public-data prototype)"},
        )

    def cone_search(self, ra_deg, dec_deg, radius_deg, limit=300):
        query = (
            f"SELECT TOP {int(limit)} {', '.join(GAIA_COLUMNS)} "
            "FROM gaiadr3.gaia_source WHERE 1=CONTAINS(POINT('ICRS', ra, dec), "
            f"CIRCLE('ICRS', {ra_deg:.10f}, {dec_deg:.10f}, {radius_deg:.10f}))"
        )
        params = {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "json", "QUERY": query}
        try:
            response = self.client.post(GAIA_TAP_URL, data=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ArchiveError("Gaia archive request failed or timed out") from exc
        try:
            payload = response.json()
            columns = [column["name"] for column in payload["metadata"]]
            rows = payload["data"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ArchiveError("Gaia archive returned an unexpected response shape") from exc
        return columns, rows


def propagate_position(ra, dec, pmra, pmdec, ref_epoch, target_year):
    """Linear proper-motion approximation (no parallax/radial-velocity term):
    good enough over a few years to tell whether a bright, fast-moving star
    has visibly shifted, not a substitute for full spherical space motion.
    """
    delta_years = target_year - (ref_epoch or 2016.0)
    dec_rad = math.radians(dec)
    new_dec = dec + pmdec * delta_years / 3.6e6
    new_ra = (ra + (pmra * delta_years / 3.6e6) / max(math.cos(dec_rad), 1e-6)) % 360
    return new_ra, new_dec


def gaia_overlay(client, request, target_iso, pixels=512, limit=300):
    """Cone-search Gaia DR3 around ``request``'s field, propagate proper
    motion to ``target_iso``, and project onto the same output grid the
    preview PNG uses (see ``imaging.output_wcs``), keeping only sources that
    land inside the rendered frame.
    """
    radius_deg = request.fov_arcmin / 60 / math.sqrt(2)
    columns, rows = client.cone_search(request.ra, request.dec, radius_deg, limit)
    index = {name: position for position, name in enumerate(columns)}
    target_year = Time(target_iso).jyear
    wcs = output_wcs(request, pixels)
    sources = []
    without_motion = 0
    for row in rows:
        ra, dec = row[index["ra"]], row[index["dec"]]
        if ra is None or dec is None:
            continue
        pmra, pmdec = row[index["pmra"]], row[index["pmdec"]]
        if pmra is not None and pmdec is not None:
            ra, dec = propagate_position(
                ra, dec, pmra, pmdec, row[index["ref_epoch"]], target_year
            )
        else:
            without_motion += 1
        x, y = wcs.world_to_pixel(SkyCoord(ra, dec, unit="deg", frame="icrs"))
        x, y = float(x), float(y)
        if not (np.isfinite(x) and np.isfinite(y)):
            continue
        if not (0 <= x <= pixels - 1 and 0 <= y <= pixels - 1):
            continue
        g_mag = row[index["phot_g_mean_mag"]] if "phot_g_mean_mag" in index else None
        source_id = row[index["source_id"]]
        source = {
            "id": str(source_id),
            "raDeg": ra,
            "decDeg": dec,
            "xFraction": x / (pixels - 1),
            "yFraction": 1 - y / (pixels - 1),
        }
        if g_mag is not None:
            source["label"] = f"Gaia DR3 {source_id} (G={g_mag:.1f})"
        sources.append(source)
    warnings = [
        "Positions use a linear proper-motion approximation from each source's own "
        "Gaia DR3 reference epoch; parallax and radial velocity are not applied.",
    ]
    if without_motion:
        warnings.append(
            f"{without_motion} source(s) had no proper-motion solution and are shown at "
            "their unpropagated Gaia DR3 catalog position."
        )
    return sources, warnings
