"""Gaia DR3 catalog overlay, with a second public TAP service for availability.

All displayed positions come from genuine Gaia DR3 catalog rows. No proxy
catalog, simulated star, or locally inferred source is used on an outage.
"""

import csv
import io
import logging
import math
import threading
import time
from collections import OrderedDict

import httpx
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.time import Time

from .archive import ArchiveError
from .imaging import output_wcs

logger = logging.getLogger(__name__)

GAIA_TAP_URL = "https://gea.esac.esa.int/tap-server/tap/sync"
# Independently operated Gaia DR3 mirror, documented at
# https://gaia.ari.uni-heidelberg.de/help.html
GAIA_MIRROR_TAP_URL = "https://gaia.ari.uni-heidelberg.de/tap/sync"
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


def _parse_gaia_csv(value: str):
    """Read ARI TAP's standard CSV without losing large Gaia source IDs."""
    reader = csv.DictReader(io.StringIO(value.lstrip("\ufeff")))
    if not reader.fieldnames:
        raise ValueError("Missing Gaia CSV header")
    names = [name.strip().lower() for name in reader.fieldnames]
    if len(set(names)) != len(names) or not set(GAIA_COLUMNS).issubset(names):
        raise ValueError("Gaia CSV response is missing required columns")

    rows = []
    for record in reader:
        normalized = {
            (key or "").strip().lower(): item.strip() if item is not None else ""
            for key, item in record.items()
        }
        row = []
        for name in GAIA_COLUMNS:
            cell = normalized.get(name, "")
            if not cell or cell.lower() in ("null", "nan", "--"):
                row.append(None)
            elif name == "source_id":
                # Gaia source IDs can exceed JavaScript's 53-bit integer range.
                row.append(cell)
            else:
                value_float = float(cell)
                row.append(value_float if math.isfinite(value_float) else None)
        rows.append(row)
    return list(GAIA_COLUMNS), rows


class GaiaClient:
    """Use ESA's Gaia TAP service, then ARI's Gaia DR3 TAP mirror on failure.

    Successful, radius-limited catalog results are cached briefly in memory.
    This avoids a fresh remote cone search every time the user changes epoch.
    """

    _CACHE_SECONDS = 900
    _CACHE_SIZE = 64

    def __init__(self, settings, transport=None):
        # A catalog overlay should not make the entire viewer hang for two minutes.
        timeout = min(float(settings.timeout_seconds), 15.0)
        self.client = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=min(timeout, 10.0)),
            transport=transport,
            headers={"User-Agent": "SPHERExSkyAPI/0.1 (public-data prototype)"},
        )
        self._cache = OrderedDict()
        self._lock = threading.Lock()

    def cone_search(self, ra_deg, dec_deg, radius_deg, limit=300):
        limit = max(1, min(int(limit), 300))
        cache_key = (round(ra_deg, 8), round(dec_deg, 8), round(radius_deg, 8), limit)
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and now - cached[0] < self._CACHE_SECONDS:
                self._cache.move_to_end(cache_key)
                return cached[1], cached[2]
            if cached:
                del self._cache[cache_key]

        query = (
            f"SELECT TOP {limit} {', '.join(GAIA_COLUMNS)} "
            "FROM gaiadr3.gaia_source WHERE 1=CONTAINS(POINT('ICRS', ra, dec), "
            f"CIRCLE('ICRS', {ra_deg:.10f}, {dec_deg:.10f}, {radius_deg:.10f})) "
            "AND phot_g_mean_mag IS NOT NULL ORDER BY phot_g_mean_mag ASC"
        )
        providers = (
            ("ESA", GAIA_TAP_URL, "json"),
            ("ARI", GAIA_MIRROR_TAP_URL, "CSV"),
        )
        errors = []
        for name, url, format_name in providers:
            params = {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": format_name, "QUERY": query}
            try:
                response = self.client.post(url, data=params)
                response.raise_for_status()
                if format_name == "json":
                    payload = response.json()
                    columns = [column["name"].lower() for column in payload["metadata"]]
                    if not set(GAIA_COLUMNS).issubset(columns):
                        raise ValueError("Gaia JSON response is missing required columns")
                    rows = payload["data"]
                    if not isinstance(rows, list):
                        raise ValueError("Gaia JSON data is not a list")
                else:
                    columns, rows = _parse_gaia_csv(response.text)
                with self._lock:
                    self._cache[cache_key] = (time.monotonic(), columns, rows)
                    self._cache.move_to_end(cache_key)
                    if len(self._cache) > self._CACHE_SIZE:
                        self._cache.popitem(last=False)
                if name != "ESA":
                    logger.info("Gaia DR3 overlay served by ARI mirror after ESA was unavailable")
                return columns, rows
            except (httpx.HTTPError, ValueError, KeyError, TypeError, csv.Error) as exc:
                errors.append((name, exc))
                logger.warning("Gaia DR3 %s catalog query failed: %s", name, exc)

        raise ArchiveError(
            "Gaia DR3 catalog temporarily unavailable from both ESA and ARI; "
            "turn off the overlay and retry later."
        ) from errors[-1][1]


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


def gaia_overlay(client, request, target_iso, pixels=512, limit=75):
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
        "Catalog markers are Gaia optical sources (G band), ordered by brightness; "
        "they are not confirmed detections in the SPHEREx infrared image.",
        "Positions use a linear proper-motion approximation from each source's own "
        "Gaia DR3 reference epoch; parallax and radial velocity are not applied.",
    ]
    if without_motion:
        warnings.append(
            f"{without_motion} source(s) had no proper-motion solution and are shown at "
            "their unpropagated Gaia DR3 catalog position."
        )
    return sources, warnings
