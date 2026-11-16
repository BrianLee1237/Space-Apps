"""Gaia DR3 catalog overlay with independent catalog providers and durable caching.

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
from astropy.io.votable import parse
from astropy.time import Time
from filelock import FileLock

from .archive import ArchiveError, CapacityError
from .imaging import output_wcs
from .storage import Store, canonical, digest

logger = logging.getLogger(__name__)

GAIA_TAP_URL = "https://gea.esac.esa.int/tap-server/tap/sync"
# Independently operated Gaia DR3 mirror, documented at
# https://gaia.ari.uni-heidelberg.de/help.html
GAIA_MIRROR_TAP_URL = "https://gaia.ari.uni-heidelberg.de/tap/sync"
GAIA_VIZIER_URL = "https://vizier.cfa.harvard.edu/viz-bin/votable"
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


def _parse_vizier(payload):
    """Read the published I/355 Gaia DR3 subset at its reference epoch 2016.0."""
    votable = parse(io.BytesIO(payload), verify="warn")
    for resource in votable.resources:
        for info in resource.infos:
            if info.name == "QUERY_STATUS" and info.value == "ERROR":
                raise ArchiveError(f"VizieR query failed: {info.content}")
    first_table = votable.get_first_table()
    if first_table is None:
        raise ValueError("VizieR response contains no catalog table")
    table = first_table.to_table(use_names_over_ids=True)
    names = ("Source", "RA_ICRS", "DE_ICRS", "Gmag", "pmRA", "pmDE", "Plx")
    if not set(names).issubset(table.colnames):
        raise ValueError("Gaia VizieR response is missing required columns")
    rows = []
    for entry in table:
        row = []
        for name in names:
            value = entry[name]
            if np.ma.is_masked(value):
                row.append(None)
            elif name == "Source":
                row.append(str(value))
            else:
                value = float(value)
                row.append(value if math.isfinite(value) else None)
        rows.append([*row, 2016.0])
    return list(GAIA_COLUMNS), rows


class GaiaClient:
    """Query independent Gaia DR3 mirrors and share persistent cone-search results."""

    _CACHE_SECONDS = 900
    _CACHE_SIZE = 64
    _COOLDOWN_SECONDS = 60

    def __init__(self, settings, transport=None, store=None):
        timeout = min(float(settings.timeout_seconds), 12.0)
        self.client = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=min(timeout, 3.0)),
            follow_redirects=True,
            transport=transport,
            headers={"User-Agent": "SkyframeObservatory/0.1 (public-data viewer)"},
        )
        self.store = store or Store(settings)
        self._cache = OrderedDict()
        self._lock = threading.Lock()
        self._unavailable_until = {}
        self._preferred = None

    def cone_search(self, ra_deg, dec_deg, radius_deg, limit=300):
        result = self.query_result(ra_deg, dec_deg, radius_deg, limit)
        return result["columns"], result["rows"]

    def query_result(self, ra_deg, dec_deg, radius_deg, limit=300):
        limit = max(1, min(int(limit), 300))
        key = digest(canonical([round(ra_deg, 8), round(dec_deg, 8), round(radius_deg, 8), limit]))
        # Browser cancellation does not stop a server thread. Serialize identical
        # cones so playback does not launch one remote request for every epoch.
        with FileLock(str(self.store.path("catalogs", key, ".lock")), timeout=45):
            with self._lock:
                cached = self._cache.get(key)
            if cached is None:
                try:
                    cached = self.store.read("catalogs", key)
                except (KeyError, ValueError):
                    pass
            if cached and (
                not isinstance(cached, dict)
                or not {"retrievedUnix", "columns", "rows", "provider"}.issubset(cached)
                or not isinstance(cached["retrievedUnix"], (int, float))
            ):
                cached = None
            if cached and time.time() - cached["retrievedUnix"] < self._CACHE_SECONDS:
                self._remember(key, cached)
                return {**cached, "cacheHit": True, "stale": False}

            query = (
                f"SELECT TOP {limit} {', '.join(GAIA_COLUMNS)} "
                "FROM gaiadr3.gaia_source WHERE 1=CONTAINS(POINT('ICRS', ra, dec), "
                f"CIRCLE('ICRS', {ra_deg:.10f}, {dec_deg:.10f}, {radius_deg:.10f})) "
                "AND phot_g_mean_mag IS NOT NULL ORDER BY phot_g_mean_mag ASC"
            )
            providers = [
                ("Harvard VizieR", GAIA_VIZIER_URL, "votable"),
                ("ESA", GAIA_TAP_URL, "json"),
                ("ARI", GAIA_MIRROR_TAP_URL, "CSV"),
            ]
            with self._lock:
                preferred = self._preferred
            providers.sort(key=lambda item: item[0] != preferred)
            errors = []
            for name, url, format_name in providers:
                with self._lock:
                    unavailable = self._unavailable_until.get(name, 0) > time.monotonic()
                if unavailable:
                    continue
                params = (
                    {
                        "-source": "I/355/gaiadr3",
                        "-c": f"{ra_deg:.10f} {dec_deg:.10f}",
                        "-c.rs": f"{radius_deg * 3600:.6f}",
                        "-out": "Source,RA_ICRS,DE_ICRS,Gmag,pmRA,pmDE,Plx",
                        "-out.max": str(limit),
                        "-sort": "Gmag",
                    }
                    if format_name == "votable"
                    else {
                        "REQUEST": "doQuery",
                        "LANG": "ADQL",
                        "FORMAT": format_name,
                        "QUERY": query,
                    }
                )
                try:
                    response = self.client.get(url, params=params)
                    response.raise_for_status()
                    if format_name == "votable":
                        columns, rows = _parse_vizier(response.content)
                    elif format_name == "json":
                        payload = response.json()
                        columns = [column["name"].lower() for column in payload["metadata"]]
                        rows = payload["data"]
                    else:
                        columns, rows = _parse_gaia_csv(response.text)
                    if not set(GAIA_COLUMNS).issubset(columns) or not isinstance(rows, list):
                        raise ValueError("Gaia response is missing required columns or rows")
                    if any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
                        raise ValueError("Gaia response contains malformed rows")
                    result = {
                        "columns": columns,
                        "rows": rows,
                        "provider": name,
                        "retrievedUnix": time.time(),
                        "cacheHit": False,
                        "stale": False,
                    }
                    canonical(result)
                    self._remember(key, result)
                    # A catalog result remains usable if the temporary disk budget
                    # is full. Its origin and retrieval time still accompany it.
                    try:
                        self.store.write("catalogs", key, result)
                    except (CapacityError, OSError):
                        logger.warning("Could not persist Gaia cone-search cache")
                    with self._lock:
                        self._preferred = name
                        self._unavailable_until.pop(name, None)
                    return result
                except (
                    httpx.HTTPError,
                    ArchiveError,
                    ValueError,
                    KeyError,
                    TypeError,
                    csv.Error,
                ) as exc:
                    errors.append((name, exc))
                    with self._lock:
                        self._unavailable_until[name] = time.monotonic() + self._COOLDOWN_SECONDS
                    logger.warning("Gaia DR3 %s catalog query failed: %s", name, exc)
            if cached:
                return {**cached, "cacheHit": True, "stale": True}
            detail = (
                "; ".join(name for name, _ in errors) or "providers are cooling down after errors"
            )
            raise ArchiveError(
                "Gaia DR3 is temporarily unavailable from Harvard VizieR, ESA, and ARI. "
                f"Retry shortly. Failed queries: {detail}."
            ) from (errors[-1][1] if errors else None)

    def _remember(self, key, result):
        with self._lock:
            self._cache[key] = result
            self._cache.move_to_end(key)
            if len(self._cache) > self._CACHE_SIZE:
                self._cache.popitem(last=False)


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
    catalog = client.query_result(request.ra, request.dec, radius_deg, limit)
    columns, rows = catalog["columns"], catalog["rows"]
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
            ra, dec = propagate_position(ra, dec, pmra, pmdec, row[index["ref_epoch"]], target_year)
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
        f"Gaia DR3 catalog provider: {catalog['provider']}. "
        f"Retrieved {Time(catalog['retrievedUnix'], format='unix').isot} UTC.",
        "Catalog markers are Gaia optical sources (G band), ordered by brightness; "
        "they are not confirmed detections in the SPHEREx infrared image.",
        "Positions use a linear proper-motion approximation from each source's own "
        "Gaia DR3 reference epoch; parallax and radial velocity are not applied.",
    ]
    if catalog["stale"]:
        warnings.append(
            "Using previously retrieved Gaia DR3 catalog rows while live providers are unavailable."
        )
    if without_motion:
        warnings.append(
            f"{without_motion} source(s) had no proper-motion solution and are shown at "
            "their unpropagated Gaia DR3 catalog position."
        )
    return sources, warnings
